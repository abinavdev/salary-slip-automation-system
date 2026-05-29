import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from sqlalchemy import or_, text
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename

from config import get_config, mask_database_uri
from models import EmailLog, Employee, SalaryRecord, UploadLog, db
from utils.auth import register_auth_middleware, verify_admin_credentials
from utils.csv_parser import parse_employee_csv, parse_salary_csv
from utils.datetime_util import utc_now
from utils.db_migrate import upgrade_schema
from utils.logging_config import configure_logging
from utils.paths import get_pdf_folder, get_upload_folder, verify_writable_directory
from utils.dob_util import DobValidationError, format_dob_display, parse_dob
from utils.sample_templates import (
    build_employee_sample_workbook,
    build_salary_sample_workbook,
)
from utils.slip_service import process_one_slip
from utils.ui_helpers import is_action_flash


load_dotenv()

EMPLOYEES_PER_PAGE = 15


def create_app() -> Flask:
    configure_logging()
    log = logging.getLogger(__name__)

    app = Flask(__name__)
    app.config.from_object(get_config())
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", app.config["SECRET_KEY"])
    app.config["UPLOAD_FOLDER"] = str(get_upload_folder(app.root_path))
    app.config["PDF_FOLDER"] = str(get_pdf_folder(app.root_path))

    db.init_app(app)

    @app.template_filter("dob_display")
    def dob_display_filter(value):
        return format_dob_display(value) or "-"

    @app.template_filter("is_action_flash")
    def is_action_flash_filter(message):
        return is_action_flash(message)

    if os.getenv("RENDER") or os.getenv("FLASK_ENV", "").lower() == "production":
        app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    register_auth_middleware(app)
    register_routes(app)

    with app.app_context():
        upgrade_schema(db)
        log.info(
            "App started | env=%s upload=%s pdf=%s db=%s",
            os.getenv("FLASK_ENV", "development"),
            app.config["UPLOAD_FOLDER"],
            app.config["PDF_FOLDER"],
            mask_database_uri(app.config["SQLALCHEMY_DATABASE_URI"]),
        )
        if (
            os.getenv("FLASK_ENV", "").lower() == "production"
            and app.config["SECRET_KEY"] == "dev-secret-key"
        ):
            log.warning("SECRET_KEY is still the default — set a strong value on Render.")
        if not os.getenv("ADMIN_PASSWORD"):
            log.warning("ADMIN_PASSWORD is not set — admin login will fail.")

    return app


def register_routes(app: Flask) -> None:
    @app.get("/health")
    def health():
        checks = {
            "database": False,
            "upload_folder": False,
            "pdf_folder": False,
            "sendgrid_config": False,
        }
        try:
            db.session.execute(text("SELECT 1"))
            checks["database"] = True
        except Exception as exc:
            logging.getLogger(__name__).warning("Health DB check failed: %s", exc)

        checks["upload_folder"] = verify_writable_directory(
            Path(app.config["UPLOAD_FOLDER"])
        )
        checks["pdf_folder"] = verify_writable_directory(Path(app.config["PDF_FOLDER"]))
        checks["sendgrid_config"] = bool(os.getenv("SENDGRID_API_KEY")) and bool(
            os.getenv("FROM_EMAIL")
        )

        core_ok = checks["database"] and checks["pdf_folder"] and checks["upload_folder"]
        healthy = core_ok and checks["sendgrid_config"]
        return jsonify(
            {
                "status": "ok" if healthy else "degraded",
                "env": os.getenv("FLASK_ENV", "development"),
                "checks": checks,
                "max_slips_per_request": app.config.get("MAX_SLIPS_PER_REQUEST", 1),
            }
        ), (200 if core_ok else 503)

    @app.get("/db-info")
    def db_info():
        """Temporary debug endpoint — database URI and table row counts."""
        uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        dialect_name = db.engine.dialect.name
        if dialect_name == "postgres":
            dialect_name = "postgresql"

        return jsonify(
            {
                "database_uri": mask_database_uri(uri),
                "dialect": dialect_name,
                "employee_count": Employee.query.count(),
                "salary_record_count": SalaryRecord.query.count(),
                "email_log_count": EmailLog.query.count(),
                "upload_log_count": UploadLog.query.count(),
            }
        )

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if session.get("admin_logged_in"):
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            if verify_admin_credentials(username, password):
                session["admin_logged_in"] = True
                session["admin_username"] = username
                session.permanent = True
                flash("Login successful. Welcome back!", "success")
                next_url = request.args.get("next") or url_for("dashboard")
                return redirect(next_url)
            flash("Invalid username or password.", "danger")

        return render_template("login.html")

    @app.get("/logout")
    def logout():
        session.clear()
        flash("You have been logged out.", "info")
        return redirect(url_for("login"))

    @app.get("/")
    def dashboard():
        total_employees = Employee.query.count()
        total_salary_records = SalaryRecord.query.count()
        emails_sent = EmailLog.query.filter_by(status="success").count()
        latest_uploads = (
            UploadLog.query.order_by(UploadLog.uploaded_at.desc()).limit(5).all()
        )
        total_uploads = UploadLog.query.count()
        return render_template(
            "dashboard.html",
            total_employees=total_employees,
            total_salary_records=total_salary_records,
            emails_sent=emails_sent,
            total_uploads=total_uploads,
            latest_uploads=latest_uploads,
        )

    @app.get("/employees")
    def employees_page():
        search = request.args.get("q", "").strip()
        page = request.args.get("page", 1, type=int)
        if page < 1:
            page = 1

        query = Employee.query
        if search:
            like = f"%{search}%"
            query = query.filter(
                or_(Employee.employee_id.ilike(like), Employee.name.ilike(like))
            )

        pagination = query.order_by(Employee.employee_id.asc()).paginate(
            page=page, per_page=EMPLOYEES_PER_PAGE, error_out=False
        )

        return render_template(
            "employees.html",
            employees=pagination.items,
            pagination=pagination,
            search=search,
            total_employees=pagination.total,
        )

    @app.get("/employees/edit/<employee_id>")
    def edit_employee_page(employee_id):
        employee = Employee.query.filter_by(employee_id=employee_id).first()
        if not employee:
            flash("Employee not found.", "warning")
            return redirect(url_for("employees_page"))
        return render_template("edit_employee.html", employee=employee)

    @app.post("/employees/edit/<employee_id>")
    def edit_employee(employee_id):
        employee = Employee.query.filter_by(employee_id=employee_id).first()
        if not employee:
            flash("Employee not found.", "warning")
            return redirect(url_for("employees_page"))

        try:
            employee.name = request.form.get("name", "").strip()
            employee.email = request.form.get("email", "").strip()
            employee.designation = request.form.get("designation", "").strip()
            dob_raw = request.form.get("date_of_birth", "").strip()
            employee.date_of_birth = parse_dob(dob_raw) if dob_raw else None
            employee.updated_at = utc_now()
            db.session.commit()
            flash(f"Employee {employee.employee_id} updated successfully.", "success")
        except DobValidationError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            return redirect(url_for("edit_employee_page", employee_id=employee_id))
        except Exception as exc:
            db.session.rollback()
            flash(f"Failed to update employee: {exc}", "danger")

        return redirect(url_for("employees_page"))

    @app.post("/employees/delete/<employee_id>")
    def delete_employee(employee_id):
        employee = Employee.query.filter_by(employee_id=employee_id).first()
        if not employee:
            flash("Employee not found.", "warning")
            return redirect(url_for("employees_page"))

        try:
            db.session.delete(employee)
            db.session.commit()
            flash(f"Employee {employee_id} deleted successfully.", "success")
        except Exception as exc:
            db.session.rollback()
            flash(f"Failed to delete employee: {exc}", "danger")

        return redirect(url_for("employees_page"))

    @app.get("/salary-records")
    def salary_records_page():
        selected_month = request.args.get("month", "").strip()
        selected_year = request.args.get("year", "").strip()

        query = SalaryRecord.query
        if selected_month:
            query = query.filter(SalaryRecord.month == selected_month)
        if selected_year:
            try:
                query = query.filter(SalaryRecord.year == int(selected_year))
            except ValueError:
                flash("Invalid year filter.", "warning")
                return redirect(url_for("salary_records_page"))

        records = query.order_by(
            SalaryRecord.year.desc(), SalaryRecord.month.asc(), SalaryRecord.id.desc()
        ).all()

        employee_map = {e.employee_id: e for e in Employee.query.all()}
        rows = []
        total_payroll = 0.0
        for record in records:
            employee = employee_map.get(record.employee_id)
            rows.append(
                {
                    "id": record.id,
                    "employee_id": record.employee_id,
                    "name": employee.name if employee else "N/A",
                    "base_salary": record.base_salary,
                    "hra": record.hra,
                    "allowances": record.allowances,
                    "deductions": record.deductions,
                    "net_salary": record.net_salary,
                    "month": record.month,
                    "year": record.year,
                }
            )
            total_payroll += float(record.net_salary or 0.0)

        month_options = [
            m[0]
            for m in db.session.query(SalaryRecord.month)
            .distinct()
            .order_by(SalaryRecord.month.asc())
            .all()
            if m[0]
        ]
        year_options = [
            y[0]
            for y in db.session.query(SalaryRecord.year)
            .distinct()
            .order_by(SalaryRecord.year.desc())
            .all()
            if y[0] is not None
        ]

        return render_template(
            "salary_records.html",
            records=rows,
            total_payroll=total_payroll,
            month_options=month_options,
            year_options=year_options,
            selected_month=selected_month,
            selected_year=selected_year,
        )

    @app.get("/salary-records/edit/<int:record_id>")
    def edit_salary_page(record_id):
        salary_record = SalaryRecord.query.get(record_id)
        if not salary_record:
            flash("Salary record not found.", "warning")
            return redirect(url_for("salary_records_page"))
        employee = Employee.query.filter_by(employee_id=salary_record.employee_id).first()
        return render_template("edit_salary.html", record=salary_record, employee=employee)

    @app.post("/salary-records/edit/<int:record_id>")
    def edit_salary(record_id):
        salary_record = SalaryRecord.query.get(record_id)
        if not salary_record:
            flash("Salary record not found.", "warning")
            return redirect(url_for("salary_records_page"))

        try:
            salary_record.base_salary = float(request.form.get("base_salary", 0) or 0)
            salary_record.hra = float(request.form.get("hra", 0) or 0)
            salary_record.allowances = float(request.form.get("allowances", 0) or 0)
            salary_record.deductions = float(request.form.get("deductions", 0) or 0)
            salary_record.month = request.form.get("month", "").strip()
            salary_record.year = int(
                request.form.get("year", salary_record.year) or salary_record.year
            )
            salary_record.net_salary = (
                salary_record.base_salary
                + salary_record.hra
                + salary_record.allowances
            ) - salary_record.deductions

            db.session.commit()
            flash("Salary record updated successfully.", "success")
        except Exception as exc:
            db.session.rollback()
            flash(f"Failed to update salary record: {exc}", "danger")

        return redirect(url_for("salary_records_page"))

    @app.post("/salary-records/delete/<int:record_id>")
    def delete_salary(record_id):
        salary_record = SalaryRecord.query.get(record_id)
        if not salary_record:
            flash("Salary record not found.", "warning")
            return redirect(url_for("salary_records_page"))

        try:
            db.session.delete(salary_record)
            db.session.commit()
            flash("Salary record deleted successfully.", "success")
        except Exception as exc:
            db.session.rollback()
            flash(f"Failed to delete salary record: {exc}", "danger")

        return redirect(url_for("salary_records_page"))

    @app.get("/email-logs")
    def email_logs_page():
        logs = EmailLog.query.order_by(EmailLog.sent_at.desc(), EmailLog.id.desc()).all()
        return render_template("email_logs.html", logs=logs)

    @app.post("/email-logs/clear")
    def clear_email_logs():
        try:
            db.session.query(EmailLog).delete()
            db.session.commit()
            flash("All email logs cleared.", "success")
        except Exception as exc:
            db.session.rollback()
            flash(f"Failed to clear email logs: {exc}", "danger")
        return redirect(url_for("email_logs_page"))

    @app.get("/download/sample-employees")
    def download_sample_employees():
        buffer = build_employee_sample_workbook()
        return send_file(
            buffer,
            as_attachment=True,
            download_name="sample_employee_sheet.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @app.get("/download/sample-salary")
    def download_sample_salary():
        buffer = build_salary_sample_workbook()
        return send_file(
            buffer,
            as_attachment=True,
            download_name="sample_salary_sheet.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @app.route("/upload-employees", methods=["GET", "POST"])
    def upload_employees():
        if request.method == "GET":
            return render_template("upload_employees.html")

        upload = request.files.get("file")
        if not upload or upload.filename == "":
            flash("Please select an employee CSV/Excel file.", "warning")
            return redirect(url_for("upload_employees"))

        filename = secure_filename(upload.filename)
        file_path = Path(app.config["UPLOAD_FOLDER"]) / filename
        upload.save(file_path)

        try:
            employees, dob_errors = parse_employee_csv(str(file_path))
            added_count = 0
            updated_count = 0
            now = utc_now()

            for employee_data in employees:
                employee_id = employee_data.get("employee_id", "").strip()
                if not employee_id:
                    continue

                existing = Employee.query.filter_by(employee_id=employee_id).first()
                new_dob = employee_data.get("date_of_birth")
                if existing:
                    existing.name = employee_data.get("name", "")
                    existing.email = employee_data.get("email", "")
                    existing.designation = employee_data.get("designation", "")
                    if new_dob is not None:
                        existing.date_of_birth = new_dob
                    existing.updated_at = now
                    updated_count += 1
                else:
                    db.session.add(
                        Employee(
                            employee_id=employee_id,
                            name=employee_data.get("name", ""),
                            email=employee_data.get("email", ""),
                            designation=employee_data.get("designation", ""),
                            date_of_birth=new_dob,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    added_count += 1

            db.session.add(
                UploadLog(
                    upload_type="employees",
                    file_name=filename,
                    records_added=added_count,
                    records_updated=updated_count,
                    uploaded_at=now,
                )
            )
            db.session.commit()
            flash(
                f"Employee upload successful. Added {added_count}, Updated {updated_count}.",
                "success",
            )
            if dob_errors:
                preview = "; ".join(f"{eid}: {msg}" for eid, msg in dob_errors[:5])
                suffix = f" (+{len(dob_errors) - 5} more)" if len(dob_errors) > 5 else ""
                flash(
                    f"{len(dob_errors)} row(s) had invalid Date of Birth and were imported "
                    f"without updating DOB: {preview}{suffix}",
                    "warning",
                )
            return redirect(url_for("dashboard"))
        except Exception as exc:
            db.session.rollback()
            flash(f"Employee upload failed: {exc}", "danger")
            return redirect(url_for("upload_employees"))

    @app.route("/upload-salary", methods=["GET", "POST"])
    def upload_salary():
        if request.method == "GET":
            return render_template("upload_salary.html")

        upload = request.files.get("file")
        if not upload or upload.filename == "":
            flash("Please select a salary CSV/Excel file.", "warning")
            return redirect(url_for("upload_salary"))

        filename = secure_filename(upload.filename)
        file_path = Path(app.config["UPLOAD_FOLDER"]) / filename
        upload.save(file_path)

        try:
            salary_rows = parse_salary_csv(str(file_path))
            row_ids = [
                str(row.get("employee_id", "")).strip()
                for row in salary_rows
                if str(row.get("employee_id", "")).strip()
            ]
            if row_ids:
                known_ids = {
                    e.employee_id
                    for e in Employee.query.filter(Employee.employee_id.in_(row_ids)).all()
                }
            else:
                known_ids = set()
            missing_ids = sorted({eid for eid in row_ids if eid not in known_ids})
            if missing_ids:
                preview = ", ".join(missing_ids[:15])
                suffix = "..." if len(missing_ids) > 15 else ""
                flash(
                    f"Salary upload rejected. Unknown Employee ID(s): {preview}{suffix}. "
                    "Upload employees first.",
                    "danger",
                )
                return redirect(url_for("upload_salary"))

            inserted_count = 0
            updated_count = 0
            latest_month = None
            latest_year = None

            for row in salary_rows:
                employee_id = str(row.get("employee_id", "")).strip()
                if not employee_id:
                    continue

                month = row.get("month", "")
                year = int(row.get("year", 0))

                existing = SalaryRecord.query.filter_by(
                    employee_id=employee_id,
                    month=month,
                    year=year,
                ).first()

                if existing:
                    existing.base_salary = float(row.get("base_salary", 0.0))
                    existing.hra = float(row.get("hra", 0.0))
                    existing.allowances = float(row.get("allowances", 0.0))
                    existing.deductions = float(row.get("deductions", 0.0))
                    existing.net_salary = float(row.get("net_salary", 0.0))
                    updated_count += 1
                else:
                    db.session.add(
                        SalaryRecord(
                            employee_id=employee_id,
                            base_salary=float(row.get("base_salary", 0.0)),
                            hra=float(row.get("hra", 0.0)),
                            allowances=float(row.get("allowances", 0.0)),
                            deductions=float(row.get("deductions", 0.0)),
                            net_salary=float(row.get("net_salary", 0.0)),
                            month=month,
                            year=year,
                        )
                    )
                    inserted_count += 1

                latest_month = month
                latest_year = year

            now = utc_now()
            db.session.add(
                UploadLog(
                    upload_type="salary",
                    file_name=filename,
                    records_added=inserted_count,
                    records_updated=updated_count,
                    uploaded_at=now,
                )
            )
            db.session.commit()

            if latest_month and latest_year:
                session["preview_month"] = latest_month
                session["preview_year"] = latest_year

            flash(
                f"Salary upload successful. Added {inserted_count}, Updated {updated_count}.",
                "success",
            )
            return redirect(url_for("preview"))
        except Exception as exc:
            db.session.rollback()
            flash(f"Salary upload failed: {exc}", "danger")
            return redirect(url_for("upload_salary"))

    @app.get("/preview")
    def preview():
        month = session.get("preview_month")
        year = session.get("preview_year")

        if month and year:
            records = (
                SalaryRecord.query.filter_by(month=month, year=int(year))
                .order_by(SalaryRecord.id.desc())
                .all()
            )
        else:
            latest = SalaryRecord.query.order_by(SalaryRecord.id.desc()).first()
            if latest:
                month = latest.month
                year = latest.year
                records = (
                    SalaryRecord.query.filter_by(month=month, year=year)
                    .order_by(SalaryRecord.id.desc())
                    .all()
                )
            else:
                records = []

        preview_rows = []
        for record in records:
            employee = Employee.query.filter_by(employee_id=record.employee_id).first()
            preview_rows.append(
                {
                    "employee_id": record.employee_id,
                    "name": employee.name if employee else "N/A",
                    "designation": employee.designation if employee else "N/A",
                    "base_salary": record.base_salary,
                    "hra": record.hra,
                    "allowances": record.allowances,
                    "deductions": record.deductions,
                    "net_salary": record.net_salary,
                    "month": record.month,
                    "year": record.year,
                }
            )

        return render_template("preview.html", records=preview_rows, month=month, year=year)

    @app.post("/generate-and-send")
    def generate_and_send():
        payload = request.get_json(silent=True) or {}
        raw_selected = payload.get("selected_ids", [])
        if not isinstance(raw_selected, list):
            raw_selected = []

        seen_ids: set[str] = set()
        selected_ids: list[str] = []
        for employee_id in raw_selected:
            eid = str(employee_id).strip()
            if eid and eid not in seen_ids:
                seen_ids.add(eid)
                selected_ids.append(eid)

        log = logging.getLogger(__name__)
        log.info(
            "slip-dispatch request | raw_selected=%s unique_selected=%s ids=%s",
            len(raw_selected),
            len(selected_ids),
            selected_ids,
        )

        month = session.get("preview_month")
        year = session.get("preview_year")

        salary_records = []
        if month and year:
            salary_records = SalaryRecord.query.filter_by(month=month, year=int(year)).all()
        else:
            latest = SalaryRecord.query.order_by(SalaryRecord.id.desc()).first()
            if latest:
                month = latest.month
                year = latest.year
                salary_records = SalaryRecord.query.filter_by(month=month, year=year).all()

        if selected_ids:
            selected_set = set(selected_ids)
            salary_records = [
                r for r in salary_records if str(r.employee_id).strip() in selected_set
            ]

        records_by_employee: dict[str, SalaryRecord] = {}
        for record in salary_records:
            eid = str(record.employee_id).strip()
            if eid and eid not in records_by_employee:
                records_by_employee[eid] = record
        salary_records = list(records_by_employee.values())

        log.info(
            "slip-dispatch records | month=%s year=%s to_process=%s employee_ids=%s",
            month,
            year,
            len(salary_records),
            [str(r.employee_id) for r in salary_records],
        )

        if not salary_records:
            return jsonify(
                {
                    "success": False,
                    "total": 0,
                    "sent": 0,
                    "failed": 0,
                    "message": "No salary records found.",
                }
            ), 404

        batch_limit = int(app.config.get("MAX_SLIPS_PER_REQUEST", 1))
        if len(salary_records) > batch_limit:
            return jsonify(
                {
                    "success": False,
                    "total": len(salary_records),
                    "sent": 0,
                    "failed": 0,
                    "message": (
                        f"Too many employees in one request ({len(salary_records)}). "
                        f"Maximum per request is {batch_limit}."
                    ),
                    "batch_limit": batch_limit,
                }
            ), 400

        sent = 0
        failed = 0
        passwords = []
        last_error = None
        errors = []

        for record in salary_records:
            try:
                log.info(
                    "slip-dispatch processing | employee_id=%s month=%s year=%s",
                    record.employee_id,
                    record.month,
                    record.year,
                )
                employee = Employee.query.filter_by(employee_id=record.employee_id).first()
                result = process_one_slip(
                    record,
                    employee,
                    app.config["PDF_FOLDER"],
                    db.session,
                    EmailLog,
                )
                if result["ok"]:
                    sent += 1
                    if result["password"]:
                        passwords.append(
                            {
                                "employee": result["employee_name"],
                                "password": result["password"],
                            }
                        )
                else:
                    failed += 1
                    last_error = result["error"]
                    if last_error:
                        errors.append(last_error)
            except Exception as e:
                failed += 1
                last_error = str(e)
                errors.append(last_error)
                log.exception("Error for record %s", record.employee_id)
                db.session.add(
                    EmailLog(
                        employee_id=record.employee_id,
                        employee_name="Unknown",
                        month=record.month,
                        year=record.year,
                        sent_at=utc_now(),
                        status="failed",
                    )
                )

        db.session.commit()
        total = len(salary_records)
        return jsonify(
            {
                "success": sent > 0 and failed < total,
                "total": total,
                "sent": sent,
                "failed": failed,
                "passwords": passwords,
                "error": last_error if failed > 0 else None,
                "errors": errors[:5],
            }
        )


app = create_app()


if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "1").lower() in ("1", "true")
    port = int(os.getenv("PORT", "5000"))
    app.run(debug=debug, host="0.0.0.0", port=port)
