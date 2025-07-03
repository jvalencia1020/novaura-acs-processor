from django.utils import timezone
import pytz
from datetime import datetime
from typing import Union, Optional

def get_timezone(tz_name: str) -> pytz.timezone:
    """
    Get a timezone object from a timezone name.
    Falls back to UTC if the timezone is invalid.
    """
    try:
        return pytz.timezone(tz_name)
    except pytz.exceptions.UnknownTimeZoneError:
        return pytz.UTC

def convert_to_utc(dt: Union[datetime, str], source_tz_name: str) -> datetime:
    """
    Convert a datetime or datetime string to UTC.
    
    Args:
        dt: Datetime object or string in format '%Y-%m-%dT%H:%M' or '%Y-%m-%dT%H:%M:%S'
        source_tz_name: Name of the source timezone (e.g., 'US/Eastern')
    
    Returns:
        Datetime object in UTC
    """
    source_tz = get_timezone(source_tz_name)
    
    # Handle string input
    if isinstance(dt, str):
        try:
            dt = datetime.strptime(dt, "%Y-%m-%dT%H:%M")
        except ValueError:
            dt = datetime.strptime(dt, "%Y-%m-%dT%H:%M:%S")
    
    # Handle timezone conversion
    if timezone.is_naive(dt):
        dt = source_tz.localize(dt)
    else:
        dt = dt.astimezone(source_tz)
    
    return dt.astimezone(pytz.UTC)

def convert_from_utc(dt: Union[datetime, str], target_tz_name: str) -> datetime:
    """
    Convert a UTC datetime or datetime string to a target timezone.
    
    Args:
        dt: UTC datetime object or string in format '%Y-%m-%dT%H:%M' or '%Y-%m-%dT%H:%M:%S'
        target_tz_name: Name of the target timezone (e.g., 'US/Eastern')
    
    Returns:
        Datetime object in target timezone
    """
    target_tz = get_timezone(target_tz_name)
    
    # Handle string input
    if isinstance(dt, str):
        try:
            dt = datetime.strptime(dt, "%Y-%m-%dT%H:%M")
        except ValueError:
            dt = datetime.strptime(dt, "%Y-%m-%dT%H:%M:%S")
    
    # Ensure datetime is UTC
    if timezone.is_naive(dt):
        dt = pytz.UTC.localize(dt)
    elif dt.tzinfo != pytz.UTC:
        dt = dt.astimezone(pytz.UTC)
    
    return dt.astimezone(target_tz)

def format_datetime(dt: datetime, format_str: str = "%Y-%m-%dT%H:%M") -> str:
    """
    Format a datetime object to a string.
    
    Args:
        dt: Datetime object
        format_str: Format string (default: '%Y-%m-%dT%H:%M')
    
    Returns:
        Formatted datetime string
    """
    return dt.strftime(format_str)

def parse_datetime(dt_str: str) -> datetime:
    """
    Parse a datetime string into a datetime object.
    Handles multiple common formats.
    
    Args:
        dt_str: Datetime string
    
    Returns:
        Datetime object
    """
    formats = [
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S.%fZ"
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            continue
    
    raise ValueError(f"Could not parse datetime string: {dt_str}")

def is_future(dt: datetime, buffer_minutes: int = 1) -> bool:
    """
    Check if a datetime is in the future.
    
    Args:
        dt: Datetime object to check
        buffer_minutes: Buffer time in minutes (default: 1)
    
    Returns:
        True if the datetime is in the future, False otherwise
    """
    now = timezone.now()
    time_difference_minutes = (dt - now).total_seconds() / 60
    return time_difference_minutes >= -buffer_minutes 