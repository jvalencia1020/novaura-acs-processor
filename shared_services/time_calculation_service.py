import logging
from django.utils import timezone
from datetime import timedelta, time
import pytz
from external_models.models.external_references import CampaignOperatingHours, CampaignOperatingHoursTimeSlot

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

            # Localize current_time to the schedule's timezone
            if hasattr(schedule, 'timezone') and schedule.timezone:
                try:
                    tz = pytz.timezone(schedule.timezone)
                    current_time = current_time.astimezone(tz)
                except pytz.exceptions.UnknownTimeZoneError:
                    logger.warning(f"Unknown timezone '{schedule.timezone}', using UTC")
                    current_time = current_time.astimezone(pytz.UTC)
            else:
                # If no timezone specified, assume UTC
                current_time = current_time.astimezone(pytz.UTC)

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
            # Check if we should use campaign operating hours
            if hasattr(schedule, 'campaign') and schedule.campaign and schedule.business_hours_only:
                # Get the CRM campaign which contains the operating hours
                crm_campaign = getattr(schedule.campaign, 'crm_campaign', None)
                if crm_campaign:
                    # Use campaign operating hours if available
                    next_time = self.calculate_next_campaign_operating_time(current_time, crm_campaign)
                    if next_time:
                        return next_time
            
            # Fall back to legacy business hours logic
            next_time = self.calculate_next_business_time(current_time, schedule)
            
            # Then adjust for weekends if needed
            next_time = self.adjust_for_weekends(next_time, schedule.exclude_weekends)
            
            return next_time

        except Exception as e:
            logger.exception(f"Error getting next valid time: {e}")
            return current_time

    def is_within_campaign_operating_hours(self, current_time, campaign):
        """
        Check if a given time is within the campaign's operating hours.
        
        Args:
            current_time: The time to check (UTC)
            campaign: The campaign object
            
        Returns:
            bool: True if the time is within operating hours
        """
        try:
            # If campaign is 24/7, always return True
            if campaign.is_24_7:
                return True

            # Get the day of week for the current time
            day_mapping = {
                0: 'monday',
                1: 'tuesday', 
                2: 'wednesday',
                3: 'thursday',
                4: 'friday',
                5: 'saturday',
                6: 'sunday'
            }
            day_of_week = day_mapping[current_time.weekday()]

            # Get operating hours for this day
            operating_hours = CampaignOperatingHours.objects.filter(
                campaign=campaign,
                day_of_week=day_of_week
            ).first()

            if not operating_hours:
                # No operating hours set for this day, assume closed
                return False

            if operating_hours.is_closed:
                return False

            # Check if current time falls within any time slot
            current_time_only = current_time.time()
            for time_slot in operating_hours.time_slots.all():
                if time_slot.start_time <= current_time_only < time_slot.end_time:
                    return True

            return False

        except Exception as e:
            logger.exception(f"Error checking campaign operating hours: {e}")
            return False

    def calculate_next_campaign_operating_time(self, current_time, campaign):
        """
        Calculate the next valid operating time based on campaign operating hours.
        
        Args:
            current_time: The current time to calculate from (UTC)
            campaign: The campaign object
            
        Returns:
            datetime: The next valid operating time, or None if no operating hours found
        """
        try:
            # If campaign is 24/7, return current time
            if campaign.is_24_7:
                return current_time

            # Start with current time
            next_time = current_time

            # Try to find a valid time within the next 7 days
            for _ in range(7):
                day_mapping = {
                    0: 'monday',
                    1: 'tuesday', 
                    2: 'wednesday',
                    3: 'thursday',
                    4: 'friday',
                    5: 'saturday',
                    6: 'sunday'
                }
                day_of_week = day_mapping[next_time.weekday()]

                # Get operating hours for this day
                operating_hours = CampaignOperatingHours.objects.filter(
                    campaign=campaign,
                    day_of_week=day_of_week
                ).first()

                if operating_hours and not operating_hours.is_closed:
                    # Check if current time is within any time slot
                    current_time_only = next_time.time()
                    for time_slot in operating_hours.time_slots.all():
                        if current_time_only < time_slot.start_time:
                            # Current time is before this time slot starts
                            # Return the start time of this slot
                            return timezone.make_aware(
                                timezone.datetime.combine(next_time.date(), time_slot.start_time)
                            )
                        elif time_slot.start_time <= current_time_only < time_slot.end_time:
                            # Current time is within this time slot
                            return next_time

                    # Current time is after all time slots for this day
                    # Move to next day and try again
                    next_time = next_time + timedelta(days=1)
                    next_time = timezone.make_aware(
                        timezone.datetime.combine(next_time.date(), time(0, 0))
                    )
                else:
                    # Day is closed or no operating hours set
                    # Move to next day
                    next_time = next_time + timedelta(days=1)
                    next_time = timezone.make_aware(
                        timezone.datetime.combine(next_time.date(), time(0, 0))
                    )

            # If we get here, we couldn't find a valid time within 7 days
            logger.warning(f"Could not find valid operating time for campaign {campaign.id} within 7 days")
            return None

        except Exception as e:
            logger.exception(f"Error calculating next campaign operating time: {e}")
            return None 