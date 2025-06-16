import logging
from django.utils import timezone
from datetime import timedelta, time

logger = logging.getLogger(__name__)

class TimeCalculationService:
    """
    Service for handling time-related calculations used across the application.
    Provides reusable methods for business hours, relative time calculations, and scheduling adjustments.
    """

    def calculate_next_business_time(self, current_time, schedule):
        """
        Calculate the next valid business time based on schedule settings.
        
        Args:
            current_time: The current time to calculate from
            schedule: The schedule object containing business hours settings
            
        Returns:
            datetime: The next valid business time
        """
        try:
            if not schedule.business_hours_only:
                return current_time

            # If outside business hours, move to next business day
            if current_time.time() >= schedule.end_time:
                # Move to next day
                next_day = current_time + timedelta(days=1)
                if schedule.exclude_weekends and next_day.weekday() >= 5:
                    # Skip weekend
                    next_day += timedelta(days=2)
                return timezone.make_aware(
                    timezone.datetime.combine(next_day.date(), schedule.start_time)
                )
            elif current_time.time() < schedule.start_time:
                # Move to start time today
                return timezone.make_aware(
                    timezone.datetime.combine(current_time.date(), schedule.start_time)
                )

            return current_time

        except Exception as e:
            logger.exception(f"Error calculating next business time: {e}")
            return current_time

    def calculate_relative_time(self, base_time, days=0, hours=0, minutes=0):
        """
        Calculate a time relative to a base time.
        
        Args:
            base_time: The base time to calculate from
            days: Number of days to add/subtract
            hours: Number of hours to add/subtract
            minutes: Number of minutes to add/subtract
            
        Returns:
            datetime: The calculated relative time
        """
        try:
            return base_time + timedelta(
                days=days,
                hours=hours,
                minutes=minutes
            )
        except Exception as e:
            logger.exception(f"Error calculating relative time: {e}")
            return base_time

    def adjust_for_weekends(self, time, exclude_weekends):
        """
        Adjust a time to skip weekends if needed.
        
        Args:
            time: The time to adjust
            exclude_weekends: Whether to skip weekends
            
        Returns:
            datetime: The adjusted time
        """
        try:
            if not exclude_weekends:
                return time

            while time.weekday() >= 5:  # 5 is Saturday, 6 is Sunday
                time += timedelta(days=1)

            return time

        except Exception as e:
            logger.exception(f"Error adjusting for weekends: {e}")
            return time

    def calculate_reminder_time(self, reminder, scheduled_reachout_date, use_relative_schedule):
        """
        Calculate the send time for a reminder based on its settings.
        
        Args:
            reminder: The reminder object containing timing settings
            scheduled_reachout_date: The date of the scheduled reachout
            use_relative_schedule: Whether to use relative scheduling
            
        Returns:
            datetime: The calculated reminder time
        """
        try:
            if use_relative_schedule:
                if not scheduled_reachout_date:
                    logger.warning("No scheduled reachout date provided for relative scheduling")
                    return None

                total_minutes = reminder.get_total_minutes_before()
                send_time = scheduled_reachout_date - timedelta(minutes=total_minutes)
                
                # If the calculated time is in the past, return None
                if send_time <= timezone.now():
                    logger.debug(f"Calculated send time {send_time} is in the past")
                    return None
                    
                return send_time
            else:
                # Absolute scheduling
                if reminder.days_before is not None:
                    if not scheduled_reachout_date:
                        logger.warning("No scheduled reachout date provided for absolute scheduling")
                        return None

                    send_date = scheduled_reachout_date.date() - timedelta(days=reminder.days_before)
                    if reminder.time:
                        return timezone.make_aware(
                            timezone.datetime.combine(send_date, reminder.time)
                        )
                    return timezone.make_aware(
                        timezone.datetime.combine(send_date, time(9, 0))  # Default to 9 AM
                    )

            return None

        except Exception as e:
            logger.exception(f"Error calculating reminder time: {e}")
            return None

    def is_within_business_hours(self, current_time, schedule):
        """
        Check if a given time is within business hours.
        
        Args:
            current_time: The time to check
            schedule: The schedule object containing business hours settings
            
        Returns:
            bool: True if the time is within business hours
        """
        try:
            if not schedule.business_hours_only:
                return True

            current_time = current_time.time()
            return schedule.start_time <= current_time < schedule.end_time

        except Exception as e:
            logger.exception(f"Error checking business hours: {e}")
            return False

    def get_next_valid_time(self, current_time, schedule):
        """
        Get the next valid time considering all schedule restrictions.
        
        Args:
            current_time: The current time to calculate from
            schedule: The schedule object containing all timing settings
            
        Returns:
            datetime: The next valid time
        """
        try:
            # First adjust for business hours
            next_time = self.calculate_next_business_time(current_time, schedule)
            
            # Then adjust for weekends if needed
            next_time = self.adjust_for_weekends(next_time, schedule.exclude_weekends)
            
            return next_time

        except Exception as e:
            logger.exception(f"Error getting next valid time: {e}")
            return current_time 