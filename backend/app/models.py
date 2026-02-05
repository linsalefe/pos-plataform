from sqlalchemy import Column, String, Text, DateTime, BigInteger, Integer, Boolean, ForeignKey, func, Table
from sqlalchemy.orm import relationship
from app.database import Base


contact_tags = Table(
    "contact_tags",
    Base.metadata,
    Column("contact_wa_id", String(20), ForeignKey("contacts.wa_id"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id"), primary_key=True),
)


class Channel(Base):
    __tablename__ = "channels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    phone_number = Column(String(20), nullable=False)
    phone_number_id = Column(String(50), nullable=False)
    whatsapp_token = Column(Text, nullable=False)
    waba_id = Column(String(50))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())

    contacts = relationship("Contact", back_populates="channel")
    messages = relationship("Message", back_populates="channel")


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    wa_id = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=True)
    lead_status = Column(String(30), default="novo")
    notes = Column(Text, nullable=True)
    channel_id = Column(Integer, ForeignKey("channels.id"))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    messages = relationship("Message", back_populates="contact")
    tags = relationship("Tag", secondary=contact_tags, back_populates="contacts")
    channel = relationship("Channel", back_populates="contacts")


class Message(Base):
    __tablename__ = "messages"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    wa_message_id = Column(String(255), unique=True, nullable=False, index=True)
    contact_wa_id = Column(String(20), ForeignKey("contacts.wa_id"), nullable=False, index=True)
    channel_id = Column(Integer, ForeignKey("channels.id"))
    direction = Column(String(10), nullable=False)
    message_type = Column(String(20), nullable=False)
    content = Column(Text, nullable=True)
    timestamp = Column(DateTime, nullable=False)
    status = Column(String(20), default="received")
    created_at = Column(DateTime, server_default=func.now())

    contact = relationship("Contact", back_populates="messages")
    channel = relationship("Channel", back_populates="messages")


class Tag(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False)
    color = Column(String(20), nullable=False, default="blue")
    created_at = Column(DateTime, server_default=func.now())

    contacts = relationship("Contact", secondary=contact_tags, back_populates="tags")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="atendente")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())


class ExactLead(Base):
    __tablename__ = "exact_leads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    exact_id = Column(Integer, unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    phone1 = Column(String(30), nullable=True)
    phone2 = Column(String(30), nullable=True)
    source = Column(String(100), nullable=True)
    sub_source = Column(String(100), nullable=True)
    stage = Column(String(50), nullable=True)
    funnel_id = Column(Integer, nullable=True)
    sdr_name = Column(String(255), nullable=True)
    register_date = Column(DateTime, nullable=True)
    update_date = Column(DateTime, nullable=True)
    synced_at = Column(DateTime, server_default=func.now())
