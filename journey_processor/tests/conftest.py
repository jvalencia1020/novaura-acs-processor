import os
import django
import pytest
from django.conf import settings
from django.db import connection
from external_models.models.external_references import LeadStatus

# Set the Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'acs_personalization.settings.test')

# Configure Django
django.setup()

def create_test_tables():
    """Create all necessary tables in the test database"""
    with connection.cursor() as cursor:
        # Create account table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS account (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                active BOOLEAN DEFAULT TRUE,
                created_by_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create user table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS accounts_user (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                password VARCHAR(128) NOT NULL,
                last_login TIMESTAMP NULL,
                is_superuser BOOLEAN NOT NULL DEFAULT FALSE,
                username VARCHAR(150) UNIQUE NOT NULL,
                first_name VARCHAR(150) NOT NULL,
                last_name VARCHAR(150) NOT NULL,
                email VARCHAR(254) UNIQUE NOT NULL,
                is_staff BOOLEAN NOT NULL DEFAULT FALSE,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                date_joined TIMESTAMP NOT NULL,
                phone_number VARCHAR(20),
                timezone VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create campaign table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS campaign (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(255) NOT NULL,
                account_id INTEGER NOT NULL,
                description TEXT,
                campaign_model_id INTEGER,
                active BOOLEAN DEFAULT TRUE,
                start_date TIMESTAMP,
                end_date TIMESTAMP,
                data_retention_period INTEGER DEFAULT 90,
                campaign_from_number VARCHAR(20),
                default_timezone VARCHAR(50) DEFAULT 'US/Eastern',
                appointment_deduplication_window INTEGER DEFAULT 60,
                is_24_7 BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES account (id),
                FOREIGN KEY (campaign_model_id) REFERENCES campaign_model (id)
            )
        """)
        
        # Create campaign_model table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS campaign_model (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(100) NOT NULL,
                description TEXT
            )
        """)
        
        # Create funnel table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS funnel (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER NOT NULL,
                name VARCHAR(100) NOT NULL,
                description TEXT,
                direction VARCHAR(10) NOT NULL,
                active BOOLEAN DEFAULT TRUE,
                start_date TIMESTAMP,
                end_date TIMESTAMP,
                data_retention_period INTEGER DEFAULT 90,
                pathway_id VARCHAR(250),
                created_by_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (campaign_id) REFERENCES campaign (id),
                FOREIGN KEY (created_by_id) REFERENCES accounts_user (id)
            )
        """)
        
        # Create step table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS step (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(100) NOT NULL,
                funnel_id INTEGER NOT NULL,
                "order" INTEGER NOT NULL,
                description TEXT,
                is_default BOOLEAN DEFAULT FALSE,
                step_type VARCHAR(20) DEFAULT 'awareness',
                created_by_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (funnel_id) REFERENCES funnel (id),
                FOREIGN KEY (created_by_id) REFERENCES accounts_user (id)
            )
        """)
        
        # Create lead_status table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lead_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(100) NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create lead table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lead (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER NOT NULL,
                funnel_id INTEGER,
                first_name VARCHAR(100),
                last_name VARCHAR(100),
                email VARCHAR(254),
                phone_number VARCHAR(15),
                current_step_id INTEGER,
                status_id INTEGER,
                assigned_to_id INTEGER,
                channel VARCHAR(100),
                source VARCHAR(100),
                score FLOAT DEFAULT 0,
                conversion_probability FLOAT DEFAULT 0,
                lead_type VARCHAR(10) DEFAULT 'd2c',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_updated_by_id INTEGER,
                last_contact_date TIMESTAMP,
                daily_followup_done BOOLEAN DEFAULT FALSE,
                alternate_followup_done BOOLEAN DEFAULT FALSE,
                weekly_followup_done BOOLEAN DEFAULT FALSE,
                is_qualified BOOLEAN DEFAULT FALSE,
                is_disqualified BOOLEAN DEFAULT FALSE,
                is_dead BOOLEAN DEFAULT FALSE,
                FOREIGN KEY (campaign_id) REFERENCES campaign (id),
                FOREIGN KEY (funnel_id) REFERENCES funnel (id),
                FOREIGN KEY (current_step_id) REFERENCES step (id),
                FOREIGN KEY (status_id) REFERENCES lead_status (id),
                FOREIGN KEY (assigned_to_id) REFERENCES accounts_user (id),
                FOREIGN KEY (last_updated_by_id) REFERENCES accounts_user (id)
            )
        """)

        # Create journey table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS journey (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                funnel_id INTEGER NOT NULL,
                campaign_id INTEGER NOT NULL,
                created_by_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE,
                start_date TIMESTAMP,
                end_date TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES account (id),
                FOREIGN KEY (funnel_id) REFERENCES funnel (id),
                FOREIGN KEY (campaign_id) REFERENCES campaign (id),
                FOREIGN KEY (created_by_id) REFERENCES accounts_user (id)
            )
        """)

        # Create journey_step table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS journey_step (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                journey_id INTEGER NOT NULL,
                name VARCHAR(100) NOT NULL,
                "order" INTEGER NOT NULL,
                step_type VARCHAR(50) NOT NULL,
                template_id INTEGER,
                config JSON,
                is_entry_point BOOLEAN DEFAULT FALSE,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (journey_id) REFERENCES journey (id),
                FOREIGN KEY (template_id) REFERENCES asc_messagetemplate (id)
            )
        """)

        # Create journey_step_connection table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS journey_step_connection (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_step_id INTEGER NOT NULL,
                to_step_id INTEGER NOT NULL,
                trigger_type VARCHAR(50) NOT NULL,
                delay_duration INTEGER,
                delay_unit VARCHAR(20),
                funnel_step_id INTEGER,
                event_type VARCHAR(100),
                condition_label VARCHAR(255),
                condition_type VARCHAR(50),
                field_source VARCHAR(50),
                field_name VARCHAR(255),
                field_value TEXT,
                priority INTEGER DEFAULT 1,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (from_step_id) REFERENCES journey_step (id),
                FOREIGN KEY (to_step_id) REFERENCES journey_step (id),
                FOREIGN KEY (funnel_step_id) REFERENCES step (id)
            )
        """)

        # Create journey_event table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS journey_event (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                participant_id INTEGER NOT NULL,
                journey_step_id INTEGER NOT NULL,
                event_type VARCHAR(50) NOT NULL,
                event_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metadata JSON,
                created_by_id INTEGER NOT NULL,
                FOREIGN KEY (participant_id) REFERENCES lead_nurturing_participant (id),
                FOREIGN KEY (journey_step_id) REFERENCES journey_step (id),
                FOREIGN KEY (created_by_id) REFERENCES accounts_user (id)
            )
        """)

        # Create lead_nurturing_participant table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lead_nurturing_participant (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER NOT NULL,
                nurturing_campaign_id INTEGER NOT NULL,
                current_journey_step_id INTEGER,
                status VARCHAR(20) NOT NULL,
                last_event_at TIMESTAMP,
                entered_campaign_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                exited_campaign_at TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_by_id INTEGER NOT NULL,
                last_updated_by_id INTEGER,
                last_message_sent_at TIMESTAMP,
                messages_sent_count INTEGER DEFAULT 0,
                next_scheduled_message TIMESTAMP,
                FOREIGN KEY (lead_id) REFERENCES lead (id),
                FOREIGN KEY (nurturing_campaign_id) REFERENCES acs_leadnurturingcampaign (id),
                FOREIGN KEY (current_journey_step_id) REFERENCES journey_step (id),
                FOREIGN KEY (created_by_id) REFERENCES accounts_user (id),
                FOREIGN KEY (last_updated_by_id) REFERENCES accounts_user (id)
            )
        """)

        # Create acs_leadnurturingcampaign table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS acs_leadnurturingcampaign (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                journey_id INTEGER,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                active BOOLEAN DEFAULT TRUE,
                start_date TIMESTAMP,
                end_date TIMESTAMP,
                is_ongoing BOOLEAN DEFAULT FALSE,
                status VARCHAR(20) DEFAULT 'draft',
                status_changed_at TIMESTAMP,
                status_changed_by_id INTEGER,
                auto_enroll_new_leads BOOLEAN DEFAULT FALSE,
                auto_enroll_filters JSON,
                config JSON,
                created_by_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                campaign_type VARCHAR(20) DEFAULT 'journey',
                channel VARCHAR(10),
                template_id INTEGER,
                content TEXT,
                crm_campaign_id INTEGER,
                FOREIGN KEY (account_id) REFERENCES account (id),
                FOREIGN KEY (journey_id) REFERENCES journey (id),
                FOREIGN KEY (status_changed_by_id) REFERENCES accounts_user (id),
                FOREIGN KEY (created_by_id) REFERENCES accounts_user (id),
                FOREIGN KEY (template_id) REFERENCES asc_messagetemplate (id),
                FOREIGN KEY (crm_campaign_id) REFERENCES campaign (id)
            )
        """)

        # Create asc_messagetemplate table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS asc_messagetemplate (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                template_type VARCHAR(20) NOT NULL,
                subject VARCHAR(255),
                content TEXT NOT NULL,
                variables JSON,
                is_active BOOLEAN DEFAULT TRUE,
                created_by_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (created_by_id) REFERENCES accounts_user (id)
            )
        """)

@pytest.fixture(autouse=True)
def setup_test_database():
    """Set up the test database with required tables"""
    create_test_tables()
    yield
    # Clean up after tests
    with connection.cursor() as cursor:
        # Drop tables in reverse order of dependencies
        cursor.execute("DROP TABLE IF EXISTS journey_event")
        cursor.execute("DROP TABLE IF EXISTS journey_step_connection")
        cursor.execute("DROP TABLE IF EXISTS lead_nurturing_participant")
        cursor.execute("DROP TABLE IF EXISTS acs_leadnurturingcampaign")
        cursor.execute("DROP TABLE IF EXISTS journey_step")
        cursor.execute("DROP TABLE IF EXISTS journey")
        cursor.execute("DROP TABLE IF EXISTS asc_messagetemplate")
        cursor.execute("DROP TABLE IF EXISTS lead")
        cursor.execute("DROP TABLE IF EXISTS lead_status")
        cursor.execute("DROP TABLE IF EXISTS step")
        cursor.execute("DROP TABLE IF EXISTS funnel")
        cursor.execute("DROP TABLE IF EXISTS campaign")
        cursor.execute("DROP TABLE IF EXISTS campaign_model")
        cursor.execute("DROP TABLE IF EXISTS accounts_user")
        cursor.execute("DROP TABLE IF EXISTS account")

@pytest.fixture(autouse=True)
def enable_db_access_for_all_tests(db):
    pass

@pytest.fixture
def default_lead_status():
    """Create a default lead status for testing"""
    return LeadStatus.objects.create(
        name="New",
        description="New lead status"
    ) 