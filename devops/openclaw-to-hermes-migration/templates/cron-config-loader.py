"""
Unified config loader for migrated cron jobs.
Copy this to ~/.hermes/cron/scripts/config_loader.py and customize.
"""
import yaml
from pathlib import Path

# Adjust this path based on your actual user
CONFIG_PATH = Path("/home/ubuntu/.hermes/cron/config/config.yaml")

def get_config():
    """Load the unified cron config file."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    return {}

def get_mail_config():
    """Get mail configuration section."""
    return get_config().get('mail', {})

def get_hermes_config():
    """Get Hermes configuration section."""
    return get_config().get('hermes', {})

def get_path_config():
    """Get path configuration section."""
    return get_config().get('paths', {})

# Convenience getters
def smtp_server():
    return get_mail_config().get('smtp_server', 'smtp.qq.com')

def smtp_port():
    return get_mail_config().get('smtp_port', 465)

def smtp_user():
    return get_mail_config().get('smtp_user', '')

def smtp_pass():
    return get_mail_config().get('smtp_pass', '')

def to_email():
    return get_mail_config().get('to_email', '')

def hermes_home():
    return get_hermes_config().get('home', '/home/ubuntu/.hermes')

def get_log_dir():
    return get_path_config().get('log_dir', '/home/ubuntu/.hermes/cron/logs')

def get_data_dir():
    return get_path_config().get('data_dir', '/home/ubuntu/.hermes/data')
