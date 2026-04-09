from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey,
    Integer, JSON, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class Classroom(Base):
    """Refactored to support nesting (School > Grade > Section)."""
    __tablename__ = "classrooms"

    id                  = Column(Integer, primary_key=True, index=True)
    name                = Column(String, nullable=False)
    parent_id           = Column(Integer, ForeignKey("classrooms.id"), nullable=True) # For nesting
    school_url          = Column(String, default="https://lasalle.gsepty.com")
    whatsapp_group_id   = Column(String, nullable=True)
    is_active           = Column(Boolean, default=True)
    settings            = Column(JSON, default=dict)
    created_at          = Column(DateTime, default=datetime.utcnow)

    # Self-referential relationship for hierarchy
    children = relationship("Classroom", backref=relationship("Classroom", remote_side=[id]))
    
    parents  = relationship("Parent",  back_populates="classroom")
    students = relationship("Student", back_populates="classroom")
    subjects = relationship("Subject", back_populates="classroom")
    roles    = relationship("ClassroomRole", back_populates="classroom", cascade="all, delete-orphan")


class ClassroomRole(Base):
    """Permissions per classroom: admin|delegate|sub_delegate|support."""
    __tablename__ = "classroom_roles"
    __table_args__ = (UniqueConstraint("user_jid", "classroom_id", name="uq_user_classroom_role"),)

    id           = Column(Integer, primary_key=True, index=True)
    user_jid     = Column(String, nullable=False, index=True)
    classroom_id = Column(Integer, ForeignKey("classrooms.id"), nullable=False)
    role         = Column(String, nullable=False)
    created_at   = Column(DateTime, default=datetime.utcnow)

    classroom = relationship("Classroom", back_populates="roles")


class Parent(Base):
    __tablename__ = "parents"

    id                  = Column(Integer, primary_key=True, index=True)
    first_name          = Column(String, nullable=False)
    last_name           = Column(String, nullable=False)
    whatsapp_jid        = Column(String, unique=True, nullable=False, index=True)
    classroom_id        = Column(Integer, ForeignKey("classrooms.id"), nullable=True)
    encrypted_username  = Column(Text, nullable=True)
    encrypted_password  = Column(Text, nullable=True)
    is_active           = Column(Boolean, default=True)
    registered_at       = Column(DateTime, nullable=True)
    created_at          = Column(DateTime, default=datetime.utcnow)

    classroom = relationship("Classroom", back_populates="parents")
    # Many-to-many with students via link table
    students  = relationship("StudentParent", back_populates="parent")


class Student(Base):
    __tablename__ = "students"

    id           = Column(Integer, primary_key=True)
    name         = Column(String, nullable=False)
    grade        = Column(String, nullable=False)
    classroom_id = Column(Integer, ForeignKey("classrooms.id"), nullable=True)

    classroom    = relationship("Classroom", back_populates="students")
    assignments  = relationship("Assignment", back_populates="student")
    # Many-to-many with parents
    parents      = relationship("StudentParent", back_populates="student")


class StudentParent(Base):
    """Link table to resolve multi-parent households and identify who pays."""
    __tablename__ = "student_parents"
    __table_args__ = (UniqueConstraint("student_id", "parent_id", name="uq_student_parent"),)

    id                = Column(Integer, primary_key=True, index=True)
    student_id        = Column(Integer, ForeignKey("students.id"), nullable=False)
    parent_id         = Column(Integer, ForeignKey("parents.id"), nullable=False)
    is_primary_payer  = Column(Boolean, default=True) # Solves "who pays" edge case

    student = relationship("Student", back_populates="parents")
    parent  = relationship("Parent",  back_populates="students")


class AdminAccount(Base):
    """Stored bank/Yappy accounts per admin for quick fundraiser creation."""
    __tablename__ = "admin_accounts"

    id          = Column(Integer, primary_key=True, index=True)
    admin_jid   = Column(String, nullable=False, index=True)
    label       = Column(String, nullable=False) # e.g. "Personal Yappy", "Group Bank"
    acc_type    = Column(String, nullable=False) # bank | phone
    details     = Column(Text, nullable=False)   # Account details string
    is_default  = Column(Boolean, default=False)
    created_at  = Column(DateTime, default=datetime.utcnow)


class Subject(Base):
    __tablename__ = "subjects"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    materia_id   = Column(Integer, nullable=False, unique=True, index=True)
    name         = Column(String, nullable=False)
    icon         = Column(String, nullable=True)
    classroom_id = Column(Integer, ForeignKey("classrooms.id"), nullable=True)

    classroom    = relationship("Classroom", back_populates="subjects")


class Assignment(Base):
    __tablename__ = "assignments"

    id           = Column(Integer, primary_key=True)
    student_id   = Column(Integer, ForeignKey("students.id"), primary_key=True, index=True)
    title        = Column(Text)
    type         = Column(String)
    date         = Column(String, index=True)
    created_at   = Column(String)
    subject_id   = Column(Integer, index=True)
    description  = Column(Text)
    materials    = Column(Text)
    summary      = Column(Text)
    updated_at   = Column(String)
    short_url    = Column(String)

    student = relationship("Student", back_populates="assignments")


class Fundraiser(Base):
    __tablename__ = "fundraisers"

    id                      = Column(Integer, primary_key=True, index=True)
    name                    = Column(String, nullable=False)
    account_number          = Column(String, nullable=False) # Copied from AdminAccount on create
    type                    = Column(String, nullable=False)
    fixed_amount            = Column(String, nullable=True)
    status                  = Column(String, default="active")
    created_by_jid          = Column(String, nullable=True)
    audience_classroom_ids  = Column(JSON, nullable=True)
    created_at              = Column(DateTime, default=datetime.utcnow)
    closed_at               = Column(DateTime, nullable=True)

    products     = relationship("FundraiserProduct", back_populates="fundraiser", cascade="all, delete-orphan")
    payments     = relationship("Payment", back_populates="fundraiser")


class FundraiserProduct(Base):
    __tablename__ = "fundraiser_products"
    id            = Column(Integer, primary_key=True, index=True)
    fundraiser_id = Column(Integer, ForeignKey("fundraisers.id"), nullable=False, index=True)
    name          = Column(String, nullable=False)
    price         = Column(String, nullable=False)
    sort_order    = Column(Integer, default=0)
    fundraiser    = relationship("Fundraiser", back_populates="products")


class Payment(Base):
    __tablename__ = "payments"

    id                = Column(Integer, primary_key=True, index=True)
    fundraiser_id     = Column(Integer, ForeignKey("fundraisers.id"), nullable=False, index=True)
    payer_jid         = Column(String, nullable=False, index=True)
    payer_name        = Column(String, nullable=False)
    child_name        = Column(String, nullable=True)
    amount            = Column(String, nullable=True)
    status            = Column(String, default="pending")
    submitted_at      = Column(DateTime, default=datetime.utcnow)

    fundraiser  = relationship("Fundraiser", back_populates="payments")


class Event(Base):
    __tablename__ = "events"

    id           = Column(Integer, primary_key=True, index=True)
    title        = Column(String, nullable=False)
    description  = Column(Text, nullable=True)
    date         = Column(DateTime, nullable=False)
    is_global    = Column(Boolean, default=False)
    created_at   = Column(DateTime, default=datetime.utcnow)

    audience = relationship("EventAudience", back_populates="event", cascade="all, delete-orphan")


class EventAudience(Base):
    __tablename__ = "event_audience"
    __table_args__ = (UniqueConstraint("event_id", "classroom_id", name="uq_event_audience"),)

    id           = Column(Integer, primary_key=True, index=True)
    event_id     = Column(Integer, ForeignKey("events.id"), nullable=False, index=True)
    classroom_id = Column(Integer, ForeignKey("classrooms.id"), nullable=False)

    event     = relationship("Event",     back_populates="audience")
    classroom = relationship("Classroom")


class BotStatus(Base):
    __tablename__ = "bot_status"
    id               = Column(Integer, primary_key=True)
    last_sync_at     = Column(DateTime, nullable=True)
    maintenance_msg  = Column(Text, nullable=True)
    updated_at       = Column(DateTime, default=datetime.utcnow)


class AdminSession(Base):
    __tablename__ = "admin_sessions"
    id          = Column(Integer, primary_key=True, index=True)
    phone       = Column(String, nullable=False, index=True)
    otp_code    = Column(String, nullable=False)
    expires_at  = Column(DateTime, nullable=False)
    created_at  = Column(DateTime, default=datetime.utcnow)
