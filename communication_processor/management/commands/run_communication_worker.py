from django.core.management.base import BaseCommand
from communication_processor.worker import run_worker, run_sms_worker, run_email_worker


class Command(BaseCommand):
    help = 'Run the communication processor worker to process SQS messages'

    def add_arguments(self, parser):
        parser.add_argument(
            '--worker-type',
            type=str,
            choices=['all', 'sms', 'email'],
            default='all',
            help='Type of worker to run (default: all)'
        )
        parser.add_argument(
            '--sms-queue-url',
            type=str,
            help='SMS queue URL (overrides environment variable)'
        )
        parser.add_argument(
            '--email-queue-url',
            type=str,
            help='Email queue URL (overrides environment variable)'
        )
        parser.add_argument(
            '--max-messages',
            type=int,
            default=10,
            help='Maximum number of messages to process per batch (default: 10)'
        )
        parser.add_argument(
            '--sleep-time',
            type=int,
            default=5,
            help='Sleep time between processing cycles in seconds (default: 5)'
        )

    def handle(self, *args, **options):
        worker_type = options['worker_type']
        
        # Set environment variables if provided
        if options['sms_queue_url']:
            import os
            os.environ['SMS_QUEUE_URL'] = options['sms_queue_url']
        
        if options['email_queue_url']:
            import os
            os.environ['EMAIL_QUEUE_URL'] = options['email_queue_url']
        
        self.stdout.write(
            self.style.SUCCESS(f'Starting Communication Processor Worker (Type: {worker_type})')
        )
        
        try:
            if worker_type == 'sms':
                run_sms_worker()
            elif worker_type == 'email':
                run_email_worker()
            else:
                run_worker()
                
        except KeyboardInterrupt:
            self.stdout.write(
                self.style.WARNING('Worker stopped by user')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Worker failed: {e}')
            )
            raise 