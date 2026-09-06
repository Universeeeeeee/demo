"""System configuration package.

Provides test/parameter configuration schemas (``test_config``,
``treadmill_config``, ``param_schema``) and validation helpers used across the
application.

The ``__init__.py`` is required so this directory is treated as a regular
package rather than a namespace package. Without it, running ``agent/worker.py``
directly puts ``agent/`` on ``sys.path``, which lets the ``agent.config``
subpackage shadow this top-level ``config`` package and breaks
``from config.test_config import ...`` inside the agent modules.
"""
