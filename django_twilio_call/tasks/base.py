"""Base task classes and utilities for django-twilio-call.

Provides common functionality and patterns used across all task modules.
"""

import hashlib
import logging
from typing import Any, Dict, Optional

from celery import current_task
from django.core.cache import cache
from django.db import transaction

logger = logging.getLogger(__name__)


class BaseTask:
    """Base class for all call center tasks.

    Provides common functionality like progress tracking, error handling,
    and result caching.
    """

    def __init__(self, task_name: str):
        self.task_name = task_name

    def update_progress(self, current: int, total: int, status: str, task_instance=None) -> None:
        """Update task progress.

        Args:
            current: Current step number
            total: Total number of steps
            status: Current status message
            task_instance: Celery task instance (optional)

        """
        if task_instance is None:
            task_instance = current_task

        if task_instance:
            task_instance.update_state(
                state="PROGRESS",
                meta={"current": current, "total": total, "status": status, "task_name": self.task_name},
            )

    def handle_error(self, error: Exception, context: Dict[str, Any] = None, task_instance=None) -> Dict[str, Any]:
        """Handle task errors with consistent logging and result format.

        Args:
            error: The exception that occurred
            context: Additional context for logging
            task_instance: Celery task instance (optional)

        Returns:
            Dict: Error result dictionary

        """
        context = context or {}
        error_message = str(error)

        logger.error(
            f"Error in task {self.task_name}: {error_message}",
            extra={
                "task_name": self.task_name,
                "error_type": type(error).__name__,
                "context": context,
            },
            exc_info=True,
        )

        if task_instance is None:
            task_instance = current_task

        if task_instance:
            task_instance.update_state(
                state="FAILURE",
                meta={
                    "error": error_message,
                    "error_type": type(error).__name__,
                    "task_name": self.task_name,
                    "context": context,
                },
            )

        return {
            "success": False,
            "error": error_message,
            "error_type": type(error).__name__,
            "task_name": self.task_name,
        }

    def cache_result(self, key: str, result: Any, timeout: int = 3600) -> None:
        """Cache task result.

        Args:
            key: Cache key
            result: Result to cache
            timeout: Cache timeout in seconds

        """
        cache_key = f"task_result:{self.task_name}:{key}"
        cache.set(cache_key, result, timeout)

    def get_cached_result(self, key: str) -> Any:
        """Get cached task result.

        Args:
            key: Cache key

        Returns:
            Cached result or None

        """
        cache_key = f"task_result:{self.task_name}:{key}"
        return cache.get(cache_key)

    def generate_idempotency_key(self, *args, **kwargs) -> str:
        """Generate an idempotency key for task execution.

        Args:
            *args: Task arguments
            **kwargs: Task keyword arguments

        Returns:
            str: Idempotency key

        """
        content = f"{self.task_name}:{args}:{sorted(kwargs.items())}"
        return hashlib.md5(content.encode()).hexdigest()


class ProgressTrackingMixin:
    """Mixin to add progress tracking to tasks."""

    def track_progress(self, step: int, total_steps: int, message: str, data: Dict[str, Any] = None) -> None:
        """Track and update task progress.

        Args:
            step: Current step number
            total_steps: Total number of steps
            message: Progress message
            data: Additional progress data

        """
        progress_data = {
            "current": step,
            "total": total_steps,
            "status": message,
            "percentage": int((step / total_steps) * 100) if total_steps > 0 else 0,
        }

        if data:
            progress_data["data"] = data

        if hasattr(self, "update_state"):
            self.update_state(state="PROGRESS", meta=progress_data)


class TransactionMixin:
    """Mixin to add database transaction support to tasks."""

    def run_in_transaction(self, func, *args, **kwargs):
        """Execute function within a database transaction.

        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result

        """
        with transaction.atomic():
            return func(*args, **kwargs)


class RetryMixin:
    """Mixin to add intelligent retry logic to tasks."""

    def should_retry(self, exception: Exception, retry_count: int) -> bool:
        """Determine if task should be retried based on exception type and count.

        Args:
            exception: The exception that occurred
            retry_count: Current retry count

        Returns:
            bool: Whether to retry the task

        """
        # Don't retry for certain exception types
        non_retryable_exceptions = (
            ValueError,
            TypeError,
            AttributeError,
        )

        if isinstance(exception, non_retryable_exceptions):
            return False

        # Don't retry after max attempts
        max_retries = getattr(self, "max_retries", 3)
        return retry_count < max_retries

    def get_retry_delay(self, retry_count: int) -> int:
        """Calculate retry delay with exponential backoff.

        Args:
            retry_count: Current retry count

        Returns:
            int: Delay in seconds

        """
        base_delay = getattr(self, "base_retry_delay", 60)
        max_delay = getattr(self, "max_retry_delay", 3600)

        delay = min(base_delay * (2**retry_count), max_delay)
        return delay


def create_task_execution_record(
    task_id: str, task_name: str, args: tuple = (), kwargs: Dict[str, Any] = None, queue_name: str = "default"
) -> Optional[Any]:
    """Create a task execution record for monitoring.

    Args:
        task_id: Celery task ID
        task_name: Name of the task
        args: Task arguments
        kwargs: Task keyword arguments
        queue_name: Queue name

    Returns:
        TaskExecution model instance or None

    """
    try:
        from ..models import TaskExecution

        return TaskExecution.objects.create(
            task_id=task_id,
            task_name=task_name,
            args=list(args) if args else [],
            kwargs=kwargs or {},
            queue_name=queue_name,
            status=TaskExecution.Status.PENDING,
        )
    except Exception as e:
        logger.error(f"Failed to create task execution record: {e}")
        return None


def update_task_execution_record(task_id: str, status: str, result: Any = None, error_message: str = None) -> None:
    """Update task execution record with completion status.

    Args:
        task_id: Celery task ID
        status: Task status
        result: Task result
        error_message: Error message if failed

    """
    try:
        from django.utils import timezone

        from ..models import TaskExecution

        execution = TaskExecution.objects.filter(task_id=task_id).first()
        if not execution:
            return

        execution.status = status
        execution.completed_at = timezone.now()

        if execution.started_at:
            duration = (execution.completed_at - execution.started_at).total_seconds()
            execution.duration_seconds = duration

        if result is not None:
            execution.result = result

        if error_message:
            execution.result = {"error": error_message}

        execution.save()

    except Exception as e:
        logger.error(f"Failed to update task execution record: {e}")


class BaseCallCenterTask(BaseTask, ProgressTrackingMixin, TransactionMixin, RetryMixin):
    """Comprehensive base class for all call center tasks.

    Combines all common functionality needed by call center tasks.
    """

    def __init__(self, task_name: str):
        super().__init__(task_name)
        self.max_retries = 3
        self.base_retry_delay = 60
        self.max_retry_delay = 3600

    def execute(self, *args, **kwargs):
        """Execute the task with full error handling and monitoring.

        This method should be overridden by subclasses.
        """
        raise NotImplementedError("Subclasses must implement execute method")

    def run_with_monitoring(self, task_instance, *args, **kwargs):
        """Run task with full monitoring and error handling.

        Args:
            task_instance: Celery task instance
            *args: Task arguments
            **kwargs: Task keyword arguments

        Returns:
            Task result

        """
        task_id = task_instance.request.id if task_instance else None

        # Create execution record
        execution = create_task_execution_record(task_id=task_id, task_name=self.task_name, args=args, kwargs=kwargs)

        try:
            # Mark as started
            if execution:
                from django.utils import timezone

                execution.status = execution.Status.STARTED
                execution.started_at = timezone.now()
                execution.save()

            # Execute the task
            result = self.execute(*args, **kwargs)

            # Update as successful
            update_task_execution_record(task_id=task_id, status="SUCCESS", result=result)

            return result

        except Exception as e:
            # Handle error
            error_result = self.handle_error(e, task_instance=task_instance)

            # Update as failed
            update_task_execution_record(task_id=task_id, status="FAILURE", error_message=str(e))

            # Decide whether to retry
            retry_count = getattr(task_instance, "request", {}).get("retries", 0)
            if self.should_retry(e, retry_count):
                delay = self.get_retry_delay(retry_count)
                raise task_instance.retry(countdown=delay, exc=e)

            return error_result


# ===========================================
# TASK CHAIN UTILITIES
# ===========================================


class ChainedTask:
    """Class for managing complex task workflows with dependencies.

    Supports sequential and parallel execution of related tasks.
    """

    def __init__(self, name: str):
        """Initialize chained task.

        Args:
            name: Name of the task chain

        """
        self.name = name
        self.steps = []
        self.parallel_groups = []
        self.context = {}
        self.results = {}

    def add_step(self, task_func, *args, depends_on=None, **kwargs):
        """Add a sequential step to the chain.

        Args:
            task_func: Celery task function
            *args: Task arguments
            depends_on: List of step names this depends on
            **kwargs: Task keyword arguments

        Returns:
            Step identifier

        """
        step_id = f"step_{len(self.steps)}"
        step = {
            "id": step_id,
            "task": task_func,
            "args": args,
            "kwargs": kwargs,
            "depends_on": depends_on or [],
            "status": "pending",
            "result": None,
            "error": None,
        }
        self.steps.append(step)
        return step_id

    def add_parallel_group(self, tasks):
        """Add a group of tasks to run in parallel.

        Args:
            tasks: List of (task_func, args, kwargs) tuples

        Returns:
            Group identifier

        """
        group_id = f"group_{len(self.parallel_groups)}"
        group = {"id": group_id, "tasks": [], "status": "pending", "results": [], "errors": []}

        for task_info in tasks:
            if isinstance(task_info, tuple) and len(task_info) >= 1:
                task_func = task_info[0]
                args = task_info[1] if len(task_info) > 1 else ()
                kwargs = task_info[2] if len(task_info) > 2 else {}
            else:
                task_func = task_info
                args = ()
                kwargs = {}

            task_item = {
                "task": task_func,
                "args": args,
                "kwargs": kwargs,
                "status": "pending",
                "result": None,
                "error": None,
            }
            group["tasks"].append(task_item)

        self.parallel_groups.append(group)
        return group_id

    def set_context(self, **context):
        """Set context variables for the chain.

        Args:
            **context: Context variables

        """
        self.context.update(context)

    def execute(self, progress_callback=None):
        """Execute the entire chain.

        Args:
            progress_callback: Optional callback for progress updates

        Returns:
            Dict with execution results

        """
        logger.info(f"Starting task chain: {self.name}")

        try:
            # Execute sequential steps
            for i, step in enumerate(self.steps):
                if progress_callback:
                    progress_callback(i, len(self.steps) + len(self.parallel_groups), f"Executing step {step['id']}")

                self._execute_step(step)

            # Execute parallel groups
            for i, group in enumerate(self.parallel_groups):
                if progress_callback:
                    progress_callback(
                        len(self.steps) + i,
                        len(self.steps) + len(self.parallel_groups),
                        f"Executing group {group['id']}",
                    )

                self._execute_parallel_group(group)

            # Compile results
            execution_result = {
                "chain_name": self.name,
                "status": "success",
                "steps_completed": len([s for s in self.steps if s["status"] == "success"]),
                "groups_completed": len([g for g in self.parallel_groups if g["status"] == "success"]),
                "total_steps": len(self.steps),
                "total_groups": len(self.parallel_groups),
                "results": self.results,
                "context": self.context,
            }

            logger.info(f"Task chain completed: {self.name}")
            return execution_result

        except Exception as e:
            logger.error(f"Task chain failed: {self.name} - {e}")
            return {
                "chain_name": self.name,
                "status": "failed",
                "error": str(e),
                "results": self.results,
                "context": self.context,
            }

    def _execute_step(self, step):
        """Execute a single step."""
        try:
            # Check dependencies
            for dep in step["depends_on"]:
                if dep not in self.results or not self.results[dep].get("success"):
                    raise ValueError(f"Dependency {dep} not satisfied")

            # Inject context into kwargs
            kwargs = step["kwargs"].copy()
            kwargs["chain_context"] = self.context

            # Execute task
            logger.info(f"Executing step: {step['id']}")
            result = step["task"].delay(*step["args"], **kwargs).get()

            step["status"] = "success"
            step["result"] = result
            self.results[step["id"]] = {"success": True, "result": result}

        except Exception as e:
            step["status"] = "failed"
            step["error"] = str(e)
            self.results[step["id"]] = {"success": False, "error": str(e)}
            raise

    def _execute_parallel_group(self, group):
        """Execute a parallel group of tasks."""
        from celery import group as celery_group

        try:
            logger.info(f"Executing parallel group: {group['id']}")

            # Create celery group
            task_signatures = []
            for task_item in group["tasks"]:
                kwargs = task_item["kwargs"].copy()
                kwargs["chain_context"] = self.context

                signature = task_item["task"].s(*task_item["args"], **kwargs)
                task_signatures.append(signature)

            # Execute in parallel
            job = celery_group(task_signatures)
            results = job.apply_async().get()

            # Process results
            for i, (task_item, result) in enumerate(zip(group["tasks"], results)):
                task_item["status"] = "success"
                task_item["result"] = result
                group["results"].append(result)

            group["status"] = "success"
            self.results[group["id"]] = {"success": True, "results": group["results"]}

        except Exception as e:
            group["status"] = "failed"
            group["errors"].append(str(e))
            self.results[group["id"]] = {"success": False, "error": str(e)}
            raise


class TaskGroup:
    """Utility for managing parallel task execution with aggregated results."""

    def __init__(self, name: str):
        """Initialize task group.

        Args:
            name: Name of the task group

        """
        self.name = name
        self.tasks = []
        self.results = []
        self.errors = []

    def add_task(self, task_func, *args, **kwargs):
        """Add a task to the group.

        Args:
            task_func: Celery task function
            *args: Task arguments
            **kwargs: Task keyword arguments

        """
        self.tasks.append({"task": task_func, "args": args, "kwargs": kwargs})

    def execute_parallel(self, timeout=None):
        """Execute all tasks in parallel.

        Args:
            timeout: Maximum time to wait for completion

        Returns:
            Dict with aggregated results

        """
        from celery import group

        if not self.tasks:
            return {"name": self.name, "results": [], "errors": []}

        try:
            # Create task signatures
            signatures = []
            for task_info in self.tasks:
                sig = task_info["task"].s(*task_info["args"], **task_info["kwargs"])
                signatures.append(sig)

            # Execute in parallel
            logger.info(f"Executing task group: {self.name} ({len(self.tasks)} tasks)")
            job = group(signatures)
            results = job.apply_async(timeout=timeout).get()

            # Process results
            success_count = 0
            for i, result in enumerate(results):
                if isinstance(result, dict) and result.get("success", True):
                    self.results.append(result)
                    success_count += 1
                else:
                    self.errors.append(f"Task {i}: {result}")

            return {
                "name": self.name,
                "total_tasks": len(self.tasks),
                "successful_tasks": success_count,
                "failed_tasks": len(self.errors),
                "results": self.results,
                "errors": self.errors,
                "success_rate": (success_count / len(self.tasks)) * 100 if self.tasks else 0,
            }

        except Exception as e:
            logger.error(f"Task group execution failed: {self.name} - {e}")
            return {"name": self.name, "error": str(e), "results": [], "errors": [str(e)]}

    def execute_sequential(self, stop_on_error=True):
        """Execute tasks sequentially.

        Args:
            stop_on_error: Whether to stop on first error

        Returns:
            Dict with execution results

        """
        results = []
        errors = []

        for i, task_info in enumerate(self.tasks):
            try:
                logger.info(f"Executing task {i + 1}/{len(self.tasks)} in group: {self.name}")
                result = task_info["task"].delay(*task_info["args"], **task_info["kwargs"]).get()
                results.append(result)
            except Exception as e:
                error_msg = f"Task {i}: {e}"
                errors.append(error_msg)
                logger.error(error_msg)

                if stop_on_error:
                    break

        return {
            "name": self.name,
            "total_tasks": len(self.tasks),
            "completed_tasks": len(results),
            "failed_tasks": len(errors),
            "results": results,
            "errors": errors,
        }


class ProgressAggregator:
    """Utility for aggregating progress from multiple tasks."""

    def __init__(self, total_tasks: int):
        """Initialize progress aggregator.

        Args:
            total_tasks: Total number of tasks to track

        """
        self.total_tasks = total_tasks
        self.completed_tasks = 0
        self.task_progress = {}
        self.overall_status = "Starting"

    def update_task_progress(self, task_id: str, current: int, total: int, status: str = None):
        """Update progress for a specific task.

        Args:
            task_id: Task identifier
            current: Current progress
            total: Total progress
            status: Optional status message

        """
        self.task_progress[task_id] = {
            "current": current,
            "total": total,
            "percentage": (current / total * 100) if total > 0 else 0,
            "status": status or f"{current}/{total}",
            "completed": current >= total,
        }

        # Update overall completed count
        self.completed_tasks = len([t for t in self.task_progress.values() if t["completed"]])

    def mark_task_completed(self, task_id: str, status: str = "Completed"):
        """Mark a task as completed.

        Args:
            task_id: Task identifier
            status: Completion status

        """
        if task_id not in self.task_progress:
            self.task_progress[task_id] = {"current": 0, "total": 1}

        self.task_progress[task_id].update(
            {"current": self.task_progress[task_id]["total"], "percentage": 100, "status": status, "completed": True}
        )

        self.completed_tasks = len([t for t in self.task_progress.values() if t["completed"]])

    def get_overall_progress(self):
        """Get overall progress across all tasks.

        Returns:
            Dict with overall progress information

        """
        if not self.task_progress:
            return {
                "overall_percentage": 0,
                "completed_tasks": 0,
                "total_tasks": self.total_tasks,
                "status": self.overall_status,
                "task_details": {},
            }

        # Calculate weighted average of task progress
        total_percentage = sum(task["percentage"] for task in self.task_progress.values())
        overall_percentage = total_percentage / len(self.task_progress)

        return {
            "overall_percentage": round(overall_percentage, 2),
            "completed_tasks": self.completed_tasks,
            "total_tasks": self.total_tasks,
            "remaining_tasks": self.total_tasks - self.completed_tasks,
            "status": self.overall_status,
            "task_details": self.task_progress,
        }

    def set_overall_status(self, status: str):
        """Set overall status message.

        Args:
            status: Status message

        """
        self.overall_status = status


class TaskChainBuilder:
    """Builder pattern for creating complex task chains."""

    def __init__(self, name: str):
        """Initialize chain builder.

        Args:
            name: Name of the task chain

        """
        self.chain = ChainedTask(name)

    def add_sequential_step(self, task_func, *args, depends_on=None, **kwargs):
        """Add a sequential step.

        Args:
            task_func: Task function
            *args: Task arguments
            depends_on: Dependencies
            **kwargs: Task keyword arguments

        Returns:
            Self for chaining

        """
        self.chain.add_step(task_func, *args, depends_on=depends_on, **kwargs)
        return self

    def add_parallel_tasks(self, *tasks):
        """Add parallel tasks.

        Args:
            *tasks: Task definitions

        Returns:
            Self for chaining

        """
        self.chain.add_parallel_group(tasks)
        return self

    def with_context(self, **context):
        """Add context to the chain.

        Args:
            **context: Context variables

        Returns:
            Self for chaining

        """
        self.chain.set_context(**context)
        return self

    def build(self):
        """Build the final chain.

        Returns:
            ChainedTask instance

        """
        return self.chain


# ===========================================
# ERROR PROPAGATION UTILITIES
# ===========================================


class TaskErrorPropagator:
    """Utility for handling error propagation in task chains."""

    def __init__(self):
        self.error_handlers = {}
        self.fallback_tasks = {}

    def register_error_handler(self, error_type: type, handler_func):
        """Register an error handler for specific error types.

        Args:
            error_type: Exception type to handle
            handler_func: Function to handle the error

        """
        self.error_handlers[error_type] = handler_func

    def register_fallback_task(self, task_name: str, fallback_func):
        """Register a fallback task for when a task fails.

        Args:
            task_name: Name of the task
            fallback_func: Fallback function to execute

        """
        self.fallback_tasks[task_name] = fallback_func

    def handle_task_error(self, task_name: str, error: Exception, context: dict = None):
        """Handle error from a specific task.

        Args:
            task_name: Name of the failed task
            error: Exception that occurred
            context: Task context

        Returns:
            Result from error handler or fallback task

        """
        context = context or {}

        # Try specific error handler first
        error_type = type(error)
        if error_type in self.error_handlers:
            try:
                return self.error_handlers[error_type](error, context)
            except Exception as handler_error:
                logger.error(f"Error handler failed: {handler_error}")

        # Try fallback task
        if task_name in self.fallback_tasks:
            try:
                return self.fallback_tasks[task_name](context)
            except Exception as fallback_error:
                logger.error(f"Fallback task failed: {fallback_error}")

        # No handler available
        logger.error(f"No error handler available for {task_name}: {error}")
        return None


# ===========================================
# HELPER FUNCTIONS
# ===========================================


def create_task_chain(name: str):
    """Create a new task chain with builder pattern.

    Args:
        name: Chain name

    Returns:
        TaskChainBuilder instance

    """
    return TaskChainBuilder(name)


def execute_tasks_in_parallel(*tasks, timeout=None):
    """Execute multiple tasks in parallel.

    Args:
        *tasks: Task definitions (task_func, args, kwargs) tuples
        timeout: Execution timeout

    Returns:
        Aggregated results

    """
    group = TaskGroup("ad_hoc_parallel_execution")

    for task_def in tasks:
        if isinstance(task_def, tuple):
            group.add_task(*task_def)
        else:
            group.add_task(task_def)

    return group.execute_parallel(timeout=timeout)


def monitor_task_chain_progress(chain_name: str, task_count: int):
    """Create a progress aggregator for monitoring task chains.

    Args:
        chain_name: Name of the chain
        task_count: Number of tasks to monitor

    Returns:
        ProgressAggregator instance

    """
    return ProgressAggregator(task_count)
