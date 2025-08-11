"""
Email Service Module for Notes Taker
=====================================

This module provides email functionality for sending meeting reports
as PDF attachments. It supports multiple SMTP providers and includes
professional HTML email templates.

Requirements:
- python-email-validator
- python-dotenv (optional, for .env file support)

Environment Variables Required:
- SENDER_EMAIL: Your email address
- SENDER_APP_PASSWORD: App password (for Gmail) or regular password
- SENDER_NAME: Display name (optional, defaults to "Notes Taker")
- SMTP_SERVER: SMTP server (optional, defaults to Gmail)
- SMTP_PORT: SMTP port (optional, defaults to 587)
"""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from pathlib import Path
from typing import Optional, List
from pydantic import BaseModel, EmailStr
from fastapi import HTTPException
import logging
from datetime import datetime

# Try to load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # dotenv is optional
    pass

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EmailRequest(BaseModel):
    """Email request model for API validation"""
    to_email: EmailStr
    subject: str = "Meeting Report from Notes Taker"
    message: str = "Please find your meeting report attached."
    pdf_path: str
    cc_emails: Optional[List[EmailStr]] = None
    bcc_emails: Optional[List[EmailStr]] = None


class EmailConfig:
    """Email configuration class that reads from environment variables"""
    
    def __init__(self):
        # Gmail SMTP settings by default (most common)
        self.smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.sender_email = os.getenv("SENDER_EMAIL")
        self.sender_password = os.getenv("SENDER_APP_PASSWORD") or os.getenv("SENDER_PASSWORD")
        self.sender_name = os.getenv("SENDER_NAME", "Notes Taker")
        
        # Validate required configuration
        if not self.sender_email:
            raise ValueError(
                "SENDER_EMAIL environment variable is required. "
                "Please set your email address in the .env file."
            )
        
        if not self.sender_password:
            raise ValueError(
                "SENDER_APP_PASSWORD (or SENDER_PASSWORD) environment variable is required. "
                "For Gmail, generate an App Password in your Google Account settings."
            )
    
    def __str__(self):
        return f"EmailConfig(server={self.smtp_server}:{self.smtp_port}, sender={self.sender_email})"


class EmailService:
    """Service class to handle all email operations"""
    
    def __init__(self):
        """Initialize the email service with configuration"""
        try:
            self.config = EmailConfig()
            logger.info(f"Email service initialized: {self.config}")
        except ValueError as e:
            logger.error(f"Email configuration error: {e}")
            raise
    
    def send_email_with_attachment(self, email_request: EmailRequest) -> dict:
        """
        Send email with PDF attachment
        
        Args:
            email_request: EmailRequest object containing email details
            
        Returns:
            dict: Success response with details
            
        Raises:
            HTTPException: For various error conditions
        """
        try:
            # Validate and prepare PDF file path
            pdf_file_path = self._validate_pdf_file(email_request.pdf_path)
            
            # Create and configure email message
            msg = self._create_email_message(email_request, pdf_file_path)
            
            # Send the email
            self._send_email(msg, email_request)
            
            # Log success and return response
            logger.info(f"Email sent successfully to {email_request.to_email}")
            return {
                "success": True,
                "message": f"Email sent successfully to {email_request.to_email}",
                "recipient": email_request.to_email,
                "timestamp": datetime.now().isoformat()
            }
            
        except FileNotFoundError as e:
            logger.error(f"PDF file not found: {e}")
            raise HTTPException(status_code=404, detail=str(e))
        
        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP authentication failed: {e}")
            raise HTTPException(
                status_code=401, 
                detail="Email authentication failed. Please check your email credentials and ensure 2FA/App Password is configured correctly."
            )
        
        except smtplib.SMTPRecipientsRefused as e:
            logger.error(f"Invalid recipient email address: {e}")
            raise HTTPException(
                status_code=400,
                detail="One or more recipient email addresses are invalid or refused by the server."
            )
        
        except smtplib.SMTPException as e:
            logger.error(f"SMTP error occurred: {e}")
            raise HTTPException(
                status_code=500, 
                detail=f"Failed to send email due to server error: {str(e)}"
            )
        
        except Exception as e:
            logger.error(f"Unexpected error in email service: {e}")
            raise HTTPException(
                status_code=500, 
                detail=f"An unexpected error occurred while sending email: {str(e)}"
            )
    
    def _validate_pdf_file(self, pdf_path: str) -> Path:
        """
        Validate that the PDF file exists and is accessible
        
        Args:
            pdf_path: Path to the PDF file (may start with /)
            
        Returns:
            Path: Validated Path object
            
        Raises:
            FileNotFoundError: If file doesn't exist
        """
        # Remove leading slash if present and convert to Path
        clean_path = pdf_path.lstrip('/')
        pdf_file_path = Path(clean_path)
        
        if not pdf_file_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_file_path}")
        
        if not pdf_file_path.is_file():
            raise FileNotFoundError(f"Path exists but is not a file: {pdf_file_path}")
        
        return pdf_file_path
    
    def _create_email_message(self, email_request: EmailRequest, pdf_file_path: Path) -> MIMEMultipart:
        """
        Create the complete email message with headers, body, and attachment
        
        Args:
            email_request: Email request details
            pdf_file_path: Path to the PDF file
            
        Returns:
            MIMEMultipart: Complete email message
        """
        # Create message container
        msg = MIMEMultipart()
        
        # Set email headers
        msg['From'] = f"{self.config.sender_name} <{self.config.sender_email}>"
        msg['To'] = email_request.to_email
        msg['Subject'] = email_request.subject
        
        # Add CC and BCC if provided
        if email_request.cc_emails:
            msg['Cc'] = ', '.join(email_request.cc_emails)
        
        # Create HTML email body
        html_body = self._create_html_body(email_request.message, pdf_file_path.name)
        msg.attach(MIMEText(html_body, 'html'))
        
        # Attach PDF file
        self._attach_pdf_file(msg, pdf_file_path)
        
        return msg
    
    def _create_html_body(self, custom_message: str, filename: str) -> str:
        """
        Create a professional HTML email body
        
        Args:
            custom_message: User's custom message
            filename: Name of the attached PDF file
            
        Returns:
            str: HTML formatted email body
        """
        current_time = datetime.now().strftime("%B %d, %Y at %I:%M %p")
        
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Meeting Report</title>
        </head>
        <body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff;">
                <!-- Header -->
                <div style="background: linear-gradient(135deg, #9333ea 0%, #7c3aed 100%); padding: 30px 20px; text-align: center;">
                    <h1 style="color: white; margin: 0; font-size: 28px; font-weight: bold;">📝 Notes Taker</h1>
                    <p style="color: #e0e7ff; margin: 5px 0 0 0; font-size: 16px;">Meeting Report Delivery</p>
                </div>
                
                <!-- Main Content -->
                <div style="padding: 40px 30px; background-color: #f8fafc;">
                    <h2 style="color: #1e293b; margin: 0 0 20px 0; font-size: 24px;">Your Meeting Report is Ready! 🎉</h2>
                    
                    <p style="font-size: 16px; color: #475569; margin-bottom: 25px; line-height: 1.7;">{custom_message}</p>
                    
                    <!-- File Info Box -->
                    <div style="background: white; padding: 25px; border-radius: 12px; border-left: 5px solid #9333ea; margin: 25px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                        <h3 style="margin: 0 0 15px 0; color: #9333ea; font-size: 18px; display: flex; align-items: center;">
                            📄 Attachment Details
                        </h3>
                        <table style="width: 100%; border-collapse: collapse;">
                            <tr>
                                <td style="padding: 8px 0; color: #64748b; font-weight: 600; width: 120px;">Filename:</td>
                                <td style="padding: 8px 0; color: #1e293b;">{filename}</td>
                            </tr>
                            <tr>
                                <td style="padding: 8px 0; color: #64748b; font-weight: 600;">Generated:</td>
                                <td style="padding: 8px 0; color: #1e293b;">{current_time}</td>
                            </tr>
                            <tr>
                                <td style="padding: 8px 0; color: #64748b; font-weight: 600;">Type:</td>
                                <td style="padding: 8px 0; color: #1e293b;">PDF Document</td>
                            </tr>
                        </table>
                    </div>
                    
                    <!-- Tips Section -->
                    <div style="background: #eff6ff; padding: 25px; border-radius: 12px; border: 1px solid #bfdbfe; margin: 25px 0;">
                        <h4 style="color: #1e40af; margin: 0 0 15px 0; font-size: 16px; display: flex; align-items: center;">
                            💡 What's included in your report:
                        </h4>
                        <ul style="margin: 0; padding-left: 20px; color: #475569;">
                            <li style="margin-bottom: 8px;">Complete meeting transcription</li>
                            <li style="margin-bottom: 8px;">Key discussion points and insights</li>
                            <li style="margin-bottom: 8px;">Automatically formatted for easy reading</li>
                            <li style="margin-bottom: 0;">Ready to share with your team</li>
                        </ul>
                    </div>
                    
                    <!-- Call to Action -->
                    <div style="text-align: center; margin: 35px 0;">
                        <p style="color: #64748b; margin-bottom: 20px;">The PDF report is attached to this email and ready to download.</p>
                        <div style="background: white; padding: 20px; border-radius: 8px; border: 2px dashed #d1d5db;">
                            <p style="margin: 0; color: #374151; font-weight: 600;">📎 meeting_report.pdf</p>
                            <p style="margin: 5px 0 0 0; color: #6b7280; font-size: 14px;">Click to open the attachment above</p>
                        </div>
                    </div>
                </div>
                
                <!-- Footer -->
                <div style="background-color: #1e293b; padding: 25px 30px; text-align: center;">
                    <p style="color: #94a3b8; margin: 0 0 10px 0; font-size: 14px;">
                        Generated automatically by <strong style="color: #a855f7;">Notes Taker</strong>
                    </p>
                    <p style="color: #64748b; margin: 0; font-size: 13px; font-style: italic;">
                        Making meetings more productive, one transcript at a time.
                    </p>
                </div>
            </div>
        </body>
        </html>
        """
    
    def _attach_pdf_file(self, msg: MIMEMultipart, pdf_file_path: Path):
        """
        Attach PDF file to the email message
        
        Args:
            msg: Email message to attach file to
            pdf_file_path: Path to the PDF file
        """
        try:
            with open(pdf_file_path, 'rb') as file:
                pdf_attachment = MIMEApplication(file.read(), _subtype='pdf')
                pdf_attachment.add_header(
                    'Content-Disposition', 
                    'attachment', 
                    filename=pdf_file_path.name
                )
                msg.attach(pdf_attachment)
        except Exception as e:
            raise Exception(f"Failed to attach PDF file: {str(e)}")
    
    def _send_email(self, msg: MIMEMultipart, email_request: EmailRequest):
        """
        Send the email using SMTP
        
        Args:
            msg: Complete email message
            email_request: Original request with recipient details
        """
        # Prepare recipient list (To, CC, BCC)
        recipients = [email_request.to_email]
        if email_request.cc_emails:
            recipients.extend(email_request.cc_emails)
        if email_request.bcc_emails:
            recipients.extend(email_request.bcc_emails)
        
        # Connect to SMTP server and send email
        try:
            with smtplib.SMTP(self.config.smtp_server, self.config.smtp_port) as server:
                server.starttls()  # Enable TLS encryption
                server.login(self.config.sender_email, self.config.sender_password)
                server.send_message(msg, to_addrs=recipients)
                
        except smtplib.SMTPConnectError as e:
            raise smtplib.SMTPException(f"Could not connect to SMTP server {self.config.smtp_server}:{self.config.smtp_port}")
        except smtplib.SMTPServerDisconnected as e:
            raise smtplib.SMTPException("SMTP server disconnected unexpectedly")
    
    def test_configuration(self) -> dict:
        """
        Test the email configuration without sending an email
        
        Returns:
            dict: Configuration status and details
        """
        try:
            config_info = {
                "success": True,
                "smtp_server": self.config.smtp_server,
                "smtp_port": self.config.smtp_port,
                "sender_email": self.config.sender_email,
                "sender_name": self.config.sender_name,
                "configured": True,
                "message": "Email configuration is valid and ready to use."
            }
            
            # Test SMTP connection (optional - can be resource intensive)
            try:
                with smtplib.SMTP(self.config.smtp_server, self.config.smtp_port, timeout=10) as server:
                    server.starttls()
                    # Don't actually login for testing, just check connection
                    config_info["connection_test"] = "SMTP server is reachable"
            except Exception as e:
                config_info["connection_test"] = f"Warning: Could not test SMTP connection: {str(e)}"
            
            return config_info
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": "Email configuration has errors and needs to be fixed."
            }