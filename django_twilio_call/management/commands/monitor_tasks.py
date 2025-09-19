"""Management command for monitoring async tasks and system health."""

import time
from datetime import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from ...monitoring import get_system_status, task_monitor


class Command(BaseCommand):
    """Management command for task monitoring."""

    help = "Monitor Celery task performance and system health"

    def add_arguments(self, parser):
        parser.add_argument("--task", type=str, help="Specific task to monitor")
        parser.add_argument("--health", action="store_true", help="Show system health metrics")
        parser.add_argument("--slow", action="store_true", help="Show slow-running tasks")
        parser.add_argument("--failures", action="store_true", help="Show failure analysis")
        parser.add_argument("--queues", action="store_true", help="Show queue metrics")
        parser.add_argument("--watch", action="store_true", help="Continuously monitor (refresh every 30 seconds)")
        parser.add_argument(
            "--threshold", type=int, default=30, help="Threshold in seconds for slow tasks (default: 30)"
        )
        parser.add_argument("--hours", type=int, default=24, help="Hours to analyze for failure analysis (default: 24)")

    def handle(self, *args, **options):
        """Handle the command execution."""
        if options["watch"]:
            self.watch_mode(options)
        else:
            self.single_run(options)

    def single_run(self, options):
        """Run monitoring once and exit."""
        self.stdout.write(self.style.SUCCESS(f"Task Monitoring Report - {timezone.now().isoformat()}"))
        self.stdout.write("=" * 80)

        if options["health"]:
            self.show_health()

        if options["queues"]:
            self.show_queues()

        if options["slow"]:
            self.show_slow_tasks(options["threshold"])

        if options["failures"]:
            self.show_failures(options["hours"])

        if options["task"]:
            self.show_task_details(options["task"])

        # If no specific option provided, show overview
        if not any([options["health"], options["queues"], options["slow"], options["failures"], options["task"]]):
            self.show_overview()

    def watch_mode(self, options):
        """Continuously monitor with refresh."""
        try:
            while True:
                # Clear screen
                self.stdout.write("\033[2J\033[H")

                self.stdout.write(
                    self.style.SUCCESS(f"Live Task Monitoring - {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}")
                )
                self.stdout.write("=" * 80)

                self.show_overview()

                if options["slow"]:
                    self.show_slow_tasks(options["threshold"])

                self.stdout.write("\nPress Ctrl+C to exit...")
                time.sleep(30)

        except KeyboardInterrupt:
            self.stdout.write(self.style.SUCCESS("\nMonitoring stopped."))

    def show_overview(self):
        """Show system overview."""
        self.stdout.write(self.style.HTTP_INFO("\n📊 SYSTEM OVERVIEW"))
        self.stdout.write("-" * 40)

        try:
            health = task_monitor.get_system_health()

            self.stdout.write(f"Active Tasks: {health['total_active_tasks']}")
            self.stdout.write(f"Total Executions: {health['total_executions']}")
            self.stdout.write(f"Overall Success Rate: {health['overall_success_rate']:.1f}%")
            self.stdout.write(f"Recent Success Rate: {health['recent_success_rate']:.1f}%")
            self.stdout.write(f"Recent Executions: {health['recent_executions']}")
            self.stdout.write(f"Avg Execution Time: {health['average_execution_time']:.2f}s")

            # Show status indicator
            if health["recent_success_rate"] >= 95:
                status = self.style.SUCCESS("🟢 HEALTHY")
            elif health["recent_success_rate"] >= 90:
                status = self.style.WARNING("🟡 WARNING")
            else:
                status = self.style.ERROR("🔴 CRITICAL")

            self.stdout.write(f"System Status: {status}")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error getting overview: {e}"))

    def show_health(self):
        """Show detailed health metrics."""
        self.stdout.write(self.style.HTTP_INFO("\n🏥 SYSTEM HEALTH"))
        self.stdout.write("-" * 40)

        try:
            system_status = get_system_status()
            health = system_status.get("health", {})

            for key, value in health.items():
                if isinstance(value, float):
                    self.stdout.write(f"{key.replace('_', ' ').title()}: {value:.2f}")
                else:
                    self.stdout.write(f"{key.replace('_', ' ').title()}: {value}")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error getting health data: {e}"))

    def show_queues(self):
        """Show queue metrics."""
        self.stdout.write(self.style.HTTP_INFO("\n📋 QUEUE METRICS"))
        self.stdout.write("-" * 40)

        try:
            queue_metrics = task_monitor.get_queue_metrics()

            if not queue_metrics:
                self.stdout.write("No queue data available")
                return

            # Table header
            self.stdout.write(f"{'Queue':<20} {'Active':<8} {'24h Total':<10} {'Success%':<10} {'Avg Time':<10}")
            self.stdout.write("-" * 70)

            for queue_name, metrics in queue_metrics.items():
                self.stdout.write(
                    f"{queue_name:<20} "
                    f"{metrics.get('active_tasks', 0):<8} "
                    f"{metrics.get('total_tasks_24h', 0):<10} "
                    f"{metrics.get('success_rate_24h', 0):<10.1f} "
                    f"{metrics.get('avg_duration_24h', 0):<10.2f}"
                )

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error getting queue metrics: {e}"))

    def show_slow_tasks(self, threshold):
        """Show slow-running tasks."""
        self.stdout.write(self.style.HTTP_INFO(f"\n🐌 SLOW TASKS (>{threshold}s)"))
        self.stdout.write("-" * 40)

        try:
            slow_tasks = task_monitor.get_slow_tasks(threshold)

            if not slow_tasks:
                self.stdout.write(self.style.SUCCESS("No slow tasks detected"))
                return

            # Table header
            self.stdout.write(f"{'Task':<30} {'Queue':<15} {'Duration':<10} {'Task ID':<15}")
            self.stdout.write("-" * 75)

            for task in slow_tasks:
                duration_style = self.style.WARNING if task["duration"] < 60 else self.style.ERROR
                self.stdout.write(
                    f"{task['task_name'][:29]:<30} "
                    f"{task['queue_name']:<15} "
                    f"{duration_style(f'{task["duration"]:.1f}s'):<10} "
                    f"{task['task_id'][:14]:<15}"
                )

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error getting slow tasks: {e}"))

    def show_failures(self, hours):
        """Show failure analysis."""
        self.stdout.write(self.style.HTTP_INFO(f"\n❌ FAILURE ANALYSIS ({hours}h)"))
        self.stdout.write("-" * 40)

        try:
            failures = task_monitor.get_failure_analysis(hours)

            self.stdout.write(f"Total Failures: {failures['total_failures']}")
            self.stdout.write(f"Failure Rate: {failures['failure_rate']:.2f} failures/hour")

            if failures["failure_by_task"]:
                self.stdout.write("\nFailures by Task:")
                for task_name, count in sorted(failures["failure_by_task"].items(), key=lambda x: x[1], reverse=True):
                    self.stdout.write(f"  {task_name}: {count}")

            if failures["failure_by_queue"]:
                self.stdout.write("\nFailures by Queue:")
                for queue_name, count in sorted(failures["failure_by_queue"].items(), key=lambda x: x[1], reverse=True):
                    self.stdout.write(f"  {queue_name}: {count}")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error getting failure analysis: {e}"))

    def show_task_details(self, task_name):
        """Show detailed metrics for a specific task."""
        self.stdout.write(self.style.HTTP_INFO(f"\n📈 TASK DETAILS: {task_name}"))
        self.stdout.write("-" * 40)

        try:
            metrics = task_monitor.get_task_statistics(task_name)

            if not metrics:
                self.stdout.write(self.style.ERROR(f"No metrics found for task: {task_name}"))
                return

            self.stdout.write(f"Total Executions: {metrics['total_executions']}")
            self.stdout.write(f"Successful: {metrics['successful_executions']}")
            self.stdout.write(f"Failed: {metrics['failed_executions']}")
            self.stdout.write(f"Success Rate: {metrics['success_rate']:.1f}%")
            self.stdout.write(f"Average Duration: {metrics['average_duration']:.2f}s")
            self.stdout.write(f"Min Duration: {metrics['min_duration']:.2f}s")
            self.stdout.write(f"Max Duration: {metrics['max_duration']:.2f}s")
            self.stdout.write(f"Active Tasks: {metrics['active_tasks']}")

            if metrics["last_execution"]:
                last_exec = datetime.fromtimestamp(metrics["last_execution"])
                self.stdout.write(f"Last Execution: {last_exec.strftime('%Y-%m-%d %H:%M:%S')}")

            # Get trends if available
            try:
                trends = task_monitor.get_task_performance_trends(task_name, 7)
                if trends and "daily_stats" in trends:
                    self.stdout.write("\n7-Day Trend:")
                    for day_stat in trends["daily_stats"][-7:]:  # Last 7 days
                        self.stdout.write(
                            f"  {day_stat['date']}: "
                            f"{day_stat['total_executions']} executions, "
                            f"{day_stat['success_rate']:.1f}% success"
                        )
            except Exception:
                pass  # Ignore trend errors

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error getting task details: {e}"))
