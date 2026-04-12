from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey,
    Integer, JSON, String, Text, Time, UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class Classroom(Base):
    """Refactored to support nesting (School > Grade > Section)."""
    __tablename__ = "classrooms"

    id                  = Column(Integer, primary_key=True, index=True)
    name                = Column(String, nullable=False)
    display_name        = Column(String, nullable=True)  # admin-renameable; falls back to name
    parent_id           = Column(Integer, ForeignKey("classrooms.id"), nullable=True) # For nesting
    school_url          = Column(String, default="https://lasalle.gsepty.com")
    whatsapp_group_id   = Column(String, nullable=True)
    is_active           = Column(Boolean, default=True)
    settings            = Column(JSON, default=dict)
    created_at          = Column(DateTime, default=datetime.utcnow)

    # Self-referential relationship for hierarchy
    parent_group = relationship("Classroom", remote_side=[id], backref="children")

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
    """Registered parent who manages a classroom."""
    __tablename__ = "parents"

    id                  = Column(Integer, primary_key=True, index=True)
    first_name          = Column(String, nullable=False)
    last_name           = Column(String, nullable=False)
    whatsapp_jid        = Column(String, unique=True, nullable=False, index=True)
    classroom_id        = Column(Integer, ForeignKey("classrooms.id"), nullable=True)
    encrypted_username  = Column(Text, nullable=True)
    encrypted_password  = Column(Text, nullable=True)
    student_ids         = Column(JSON, nullable=True)   # e.g. [2036, 7505]
    is_active           = Column(Boolean, default=True)
    registered_at       = Column(DateTime, nullable=True)
    created_at          = Column(DateTime, default=datetime.utcnow)

    classroom = relationship("Classroom", back_populates="parents")
    students  = relationship("StudentParent", back_populates="parent")


class Student(Base):
    __tablename__ = "students"

    id           = Column(Integer, primary_key=True)
    name         = Column(String, nullable=False)
    grade        = Column(String, nullable=False)
    classroom_id = Column(Integer, ForeignKey("classrooms.id"), nullable=True)
    parent_id    = Column(Integer, ForeignKey("parents.id"), nullable=True)

    classroom    = relationship("Classroom", back_populates="students")
    assignments  = relationship("Assignment", back_populates="student")
    # Many-to-many with parents via link table
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


class InviteCode(Base):
    """One-time codes generated by admin to let parents register."""
    __tablename__ = "invite_codes"

    id          = Column(Integer, primary_key=True, index=True)
    code        = Column(String, unique=True, nullable=False, index=True)
    label       = Column(String, nullable=True)
    status      = Column(String, default="active", nullable=False)
    created_at  = Column(DateTime, default=datetime.utcnow)
    used_at     = Column(DateTime, nullable=True)
    parent_id   = Column(Integer, ForeignKey("parents.id"), nullable=True)


class RegistrationSession(Base):
    """Tracks in-progress parent onboarding conversations."""
    __tablename__ = "registration_sessions"

    id          = Column(Integer, primary_key=True, index=True)
    chat_jid    = Column(String, unique=True, nullable=False, index=True)
    state       = Column(String, nullable=False)
    data        = Column(JSON, default=dict)
    updated_at  = Column(DateTime, default=datetime.utcnow)


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


class ConversationSession(Base):
    """Generic multi-step conversation tracker for fundraiser, payment, and contact flows."""
    __tablename__ = "conversation_sessions"

    id         = Column(Integer, primary_key=True, index=True)
    chat_jid   = Column(String, unique=True, nullable=False, index=True)
    flow       = Column(String, nullable=False)
    step       = Column(String, nullable=False)
    data       = Column(JSON, default=dict)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class KnownContact(Base):
    """Non-registered person identified via WhatsApp group membership."""
    __tablename__ = "known_contacts"

    id              = Column(Integer, primary_key=True, index=True)
    jid             = Column(String, unique=True, nullable=False, index=True)
    phone           = Column(String, nullable=True)  # resolved real phone number
    name            = Column(String, nullable=False)
    child_name      = Column(String, nullable=True)  # legacy — migrated to KnownContactGroup
    source_group_id = Column(String, nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow)

    groups = relationship("KnownContactGroup", back_populates="contact")


class KnownContactGroup(Base):
    """Cached group membership: which Classrooms a KnownContact belongs to."""
    __tablename__ = "known_contact_groups"
    __table_args__ = (UniqueConstraint("contact_jid", "classroom_id", name="uq_kcg_contact_classroom"),)

    id              = Column(Integer, primary_key=True, index=True)
    contact_jid     = Column(String, ForeignKey("known_contacts.jid"), nullable=False, index=True)
    classroom_id    = Column(Integer, ForeignKey("classrooms.id"), nullable=False)
    child_name      = Column(String, nullable=True)
    is_primary_payer = Column(Boolean, default=False)
    active          = Column(Boolean, default=True)
    synced_at       = Column(DateTime, default=datetime.utcnow)

    contact   = relationship("KnownContact", back_populates="groups")
    classroom = relationship("Classroom")


class Fundraiser(Base):
    """A fundraiser campaign created by admin."""
    __tablename__ = "fundraisers"

    id                      = Column(Integer, primary_key=True, index=True)
    name                    = Column(String, nullable=False)
    friendly_name           = Column(String, nullable=True)
    code                    = Column(String, nullable=True)
    account_number          = Column(String, nullable=False)
    type                    = Column(String, nullable=False)
    fixed_amount            = Column(String, nullable=True)
    status                  = Column(String, default="active")
    created_by_jid          = Column(String, nullable=True)
    audience_classroom_ids  = Column(JSON, nullable=True)
    created_at              = Column(DateTime, default=datetime.utcnow)
    closed_at               = Column(DateTime, nullable=True)

    products     = relationship("FundraiserProduct", back_populates="fundraiser", cascade="all, delete-orphan")
    payments     = relationship("Payment", back_populates="fundraiser")
    subscribers  = relationship("FundraiserSubscriber", back_populates="fundraiser", cascade="all, delete-orphan")


class FundraiserSubscriber(Base):
    """Extra phone numbers that receive payment notifications for a fundraiser."""
    __tablename__ = "fundraiser_subscribers"

    id            = Column(Integer, primary_key=True, index=True)
    fundraiser_id = Column(Integer, ForeignKey("fundraisers.id"), nullable=False, index=True)
    phone         = Column(String, nullable=False)
    added_at      = Column(DateTime, default=datetime.utcnow)

    fundraiser = relationship("Fundraiser", back_populates="subscribers")


class FundraiserProduct(Base):
    """Product in a variable/catalog fundraiser."""
    __tablename__ = "fundraiser_products"

    id            = Column(Integer, primary_key=True, index=True)
    fundraiser_id = Column(Integer, ForeignKey("fundraisers.id"), nullable=False, index=True)
    name          = Column(String, nullable=False)
    price         = Column(String, nullable=False)
    sort_order    = Column(Integer, default=0)

    fundraiser  = relationship("Fundraiser", back_populates="products")
    order_items = relationship("OrderItem", back_populates="product")


class Payment(Base):
    """A payment/receipt submitted for a fundraiser."""
    __tablename__ = "payments"

    id                = Column(Integer, primary_key=True, index=True)
    fundraiser_id     = Column(Integer, ForeignKey("fundraisers.id"), nullable=False, index=True)
    payer_jid         = Column(String, nullable=False, index=True)
    payer_name        = Column(String, nullable=False)
    child_name        = Column(String, nullable=True)
    amount            = Column(String, nullable=True)
    confirmation_code = Column(String, nullable=True)
    receipt_media_url = Column(String, nullable=True)
    textract_raw      = Column(JSON, nullable=True)
    confidence_score  = Column(Float, nullable=True)
    status            = Column(String, default="pending")
    flag_reason       = Column(String, nullable=True)
    submitted_at      = Column(DateTime, default=datetime.utcnow)

    fundraiser  = relationship("Fundraiser", back_populates="payments")
    order_items = relationship("OrderItem", back_populates="payment")


class OrderItem(Base):
    """Line item in a variable/catalog fundraiser order."""
    __tablename__ = "order_items"

    id         = Column(Integer, primary_key=True, index=True)
    payment_id = Column(Integer, ForeignKey("payments.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("fundraiser_products.id"), nullable=False)
    quantity   = Column(Integer, nullable=False)
    subtotal   = Column(String, nullable=False)

    payment = relationship("Payment", back_populates="order_items")
    product = relationship("FundraiserProduct", back_populates="order_items")


class Form(Base):
    """A data-collection form created by admin or a Form Manager."""
    __tablename__ = "forms"

    id                    = Column(Integer, primary_key=True, index=True)
    title                 = Column(String, nullable=False)
    description           = Column(Text, nullable=True)
    purpose               = Column(String, nullable=False)
    status                = Column(String, default="draft")
    form_code             = Column(String, unique=True, nullable=True, index=True)
    created_by_jid        = Column(String, nullable=False)
    created_at            = Column(DateTime, default=datetime.utcnow)
    opens_at              = Column(DateTime, nullable=True)
    closes_at             = Column(DateTime, nullable=True)
    archived_at           = Column(DateTime, nullable=True)
    send_group_reminders  = Column(Boolean, default=True)
    reminder_interval_days = Column(Integer, default=7)

    questions   = relationship("FormQuestion",   back_populates="form",
                               order_by="FormQuestion.order", cascade="all, delete-orphan")
    submissions = relationship("FormSubmission", back_populates="form")
    audience    = relationship("FormAudience",   back_populates="form", cascade="all, delete-orphan")


class FormQuestion(Base):
    """A single question within a form."""
    __tablename__ = "form_questions"

    id            = Column(Integer, primary_key=True, index=True)
    form_id       = Column(Integer, ForeignKey("forms.id"), nullable=False, index=True)
    order         = Column(Integer, nullable=False)
    text          = Column(Text, nullable=False)
    hint          = Column(Text, nullable=True)
    type          = Column(String, nullable=False)
    answer_scope  = Column(String, default="parent")
    required      = Column(Boolean, default=True)
    options       = Column(JSON, nullable=True)
    profile_field = Column(String, nullable=True)

    form    = relationship("Form",       back_populates="questions")
    answers = relationship("FormAnswer", back_populates="question")


class FormAudience(Base):
    """Which classrooms receive a form."""
    __tablename__ = "form_audience"
    __table_args__ = (UniqueConstraint("form_id", "classroom_id", name="uq_form_audience"),)

    id           = Column(Integer, primary_key=True, index=True)
    form_id      = Column(Integer, ForeignKey("forms.id"), nullable=False, index=True)
    classroom_id = Column(Integer, ForeignKey("classrooms.id"), nullable=False)

    form      = relationship("Form",      back_populates="audience")
    classroom = relationship("Classroom")


class FormSubmission(Base):
    """A parent's (in-progress or completed) response to a form."""
    __tablename__ = "form_submissions"

    id              = Column(Integer, primary_key=True, index=True)
    form_id         = Column(Integer, ForeignKey("forms.id"), nullable=False, index=True)
    respondent_jid  = Column(String, nullable=False, index=True)
    respondent_name = Column(String, nullable=False)
    student_id      = Column(Integer, ForeignKey("students.id"), nullable=True)
    status          = Column(String, default="in_progress")
    started_at      = Column(DateTime, default=datetime.utcnow)
    submitted_at    = Column(DateTime, nullable=True)
    last_edited_at  = Column(DateTime, nullable=True)

    form    = relationship("Form",       back_populates="submissions")
    answers = relationship("FormAnswer", back_populates="submission", cascade="all, delete-orphan")
    student = relationship("Student")


class FormReader(Base):
    """Granted read access to form results via a one-time join code."""
    __tablename__ = "form_readers"

    id         = Column(Integer, primary_key=True, index=True)
    code       = Column(String, unique=True, nullable=False, index=True)
    jid        = Column(String, unique=True, nullable=True, index=True)
    name       = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    joined_at  = Column(DateTime, nullable=True)


class FormAnswer(Base):
    """A single answer to one question in a submission."""
    __tablename__ = "form_answers"
    __table_args__ = (UniqueConstraint("submission_id", "question_id", name="uq_form_answer"),)

    id            = Column(Integer, primary_key=True, index=True)
    submission_id = Column(Integer, ForeignKey("form_submissions.id"), nullable=False, index=True)
    question_id   = Column(Integer, ForeignKey("form_questions.id"), nullable=False)
    value         = Column(Text, nullable=True)
    value_json    = Column(JSON, nullable=True)
    answered_at   = Column(DateTime, default=datetime.utcnow)

    submission = relationship("FormSubmission", back_populates="answers")
    question   = relationship("FormQuestion",   back_populates="answers")


class Event(Base):
    __tablename__ = "events"

    id           = Column(Integer, primary_key=True, index=True)
    title        = Column(String, nullable=False)
    description  = Column(Text, nullable=True)
    date         = Column(DateTime, nullable=False)
    location     = Column(String, nullable=True)
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
    """Singleton row tracking bot state: last sync time + optional maintenance message."""
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


class SeducaGroup(Base):
    """Assignment group discovered from the Seduca school portal.
    Shared across all admins — any admin can link one to their classroom.
    """
    __tablename__ = "seduca_groups"

    id               = Column(Integer, primary_key=True, index=True)
    seduca_group_id  = Column(String, unique=True, nullable=False, index=True)  # portal ID — dedupe key
    name             = Column(String, nullable=False)
    discovered_by_id = Column(Integer, ForeignKey("parents.id"), nullable=True)
    last_fetched_at  = Column(DateTime, nullable=True)
    cached_data      = Column(JSON, nullable=True)  # latest assignments snapshot

    link = relationship("ClassroomSeducaLink", back_populates="seduca_group", uselist=False)


class ClassroomSeducaLink(Base):
    """1:1 binding between a Classroom (WhatsApp group) and a SeducaGroup.
    Controls when summaries are sent and whether DM Q&A is enabled.
    """
    __tablename__ = "classroom_seduca_links"
    __table_args__ = (
        UniqueConstraint("classroom_id", name="uq_csl_classroom"),
        UniqueConstraint("seduca_group_id", name="uq_csl_seduca_group"),
    )

    id              = Column(Integer, primary_key=True, index=True)
    classroom_id    = Column(Integer, ForeignKey("classrooms.id"), nullable=False)
    seduca_group_id = Column(Integer, ForeignKey("seduca_groups.id"), nullable=False)
    summary_time    = Column(Time, nullable=False)   # local time HH:MM
    summary_day     = Column(Integer, default=0)     # 0=Monday, 6=Sunday
    answer_dms      = Column(Boolean, default=True)
    created_by_id   = Column(Integer, ForeignKey("parents.id"), nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow)

    classroom    = relationship("Classroom")
    seduca_group = relationship("SeducaGroup", back_populates="link")
