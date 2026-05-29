"""SQLAlchemy models for the salary slip application."""

from flask_sqlalchemy import SQLAlchemy

from utils.datetime_util import utc_now

db = SQLAlchemy()


class Employee(db.Model):
    __tablename__ = "employees"

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    designation = db.Column(db.String(120), nullable=False)
    date_of_birth = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class SalaryRecord(db.Model):
    __tablename__ = "salary_records"

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(
        db.String(50), db.ForeignKey("employees.employee_id"), nullable=False, index=True
    )
    base_salary = db.Column(db.Float, nullable=False, default=0.0)
    hra = db.Column(db.Float, nullable=False, default=0.0)
    allowances = db.Column(db.Float, nullable=False, default=0.0)
    deductions = db.Column(db.Float, nullable=False, default=0.0)
    net_salary = db.Column(db.Float, nullable=False, default=0.0)
    month = db.Column(db.String(20), nullable=False)
    year = db.Column(db.Integer, nullable=False)


class EmailLog(db.Model):
    __tablename__ = "email_logs"

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.String(50), nullable=False)
    employee_name = db.Column(db.String(120), nullable=False)
    month = db.Column(db.String(20), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    sent_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    status = db.Column(db.String(20), nullable=False)


class UploadLog(db.Model):
    __tablename__ = "upload_logs"

    id = db.Column(db.Integer, primary_key=True)
    upload_type = db.Column(db.String(20), nullable=False)
    file_name = db.Column(db.String(255), nullable=False)
    records_added = db.Column(db.Integer, nullable=False, default=0)
    records_updated = db.Column(db.Integer, nullable=False, default=0)
    uploaded_at = db.Column(db.DateTime, nullable=False, default=utc_now)
