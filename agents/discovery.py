"""Agent discovery system for dynamic agent loading and introspection.

Provides module scanning, dynamic agent discovery, and hot-reloading
capabilities for the SEO automation platform's agent ecosystem.
"""

import asyncio
import importlib
import inspect
import sys
import pkgutil
import os
from typing import Dict, List, Set, Optional, Type, Any, Callable
from pathlib import Path
from datetime import datetime
from collections import defaultdict

import structlog
from opentelemetry import trace

from .base import BaseAgent
from .metadata import AgentMetadata, AgentDiscoveryFilter
from .registry import get_agent_registry, AgentRegistry
from .exceptions import AgentDiscoveryError, AgentLoadingError

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)


class AgentDiscoveryConfig:
    """Configuration for agent discovery system."""
    
    def __init__(
        self,
        scan_paths: Optional[List[str]] = None,
        exclude_patterns: Optional[List[str]] = None,
        auto_reload: bool = False,
        reload_interval_seconds: float = 30.0,
        max_scan_depth: int = 3
    ):
        """
        Initialize discovery configuration.
        
        Args:
            scan_paths: Paths to scan for agents (defaults to current agents package)
            exclude_patterns: Patterns to exclude from scanning
            auto_reload: Enable automatic reloading of agent modules
            reload_interval_seconds: Interval for auto-reload checks
            max_scan_depth: Maximum directory depth for scanning
        """
        self.scan_paths = scan_paths or []
        self.exclude_patterns = exclude_patterns or ['__pycache__', '*.pyc', 'test_*']
        self.auto_reload = auto_reload
        self.reload_interval_seconds = reload_interval_seconds
        self.max_scan_depth = max_scan_depth


class AgentDiscoverySystem:
    """
    Dynamic agent discovery and loading system.
    
    Provides module introspection, automatic agent registration,
    and hot-reloading capabilities for development and production.
    
    Features:
        - Dynamic module scanning and agent discovery
        - Automatic agent registration from found modules
        - Hot-reloading support for development
        - Module dependency tracking
        - Error-tolerant agent loading
        - Performance monitoring
    """
    
    def __init__(
        self,
        registry: Optional[AgentRegistry] = None,
        config: Optional[AgentDiscoveryConfig] = None
    ):
        """
        Initialize the discovery system.
        
        Args:
            registry: Agent registry instance (uses global if None)
            config: Discovery configuration
        """
        self.registry = registry or get_agent_registry()
        self.config = config or AgentDiscoveryConfig()
        
        # Discovery state
        self._discovered_modules: Dict[str, datetime] = {}
        self._module_agents: Dict[str, List[str]] = defaultdict(list)
        self._scan_errors: Dict[str, str] = {}
        self._last_scan: Optional[datetime] = None
        self._auto_reload_task: Optional[asyncio.Task] = None
        
        # Module tracking for hot-reload
        self._module_mtimes: Dict[str, float] = {}
        self._loaded_agent_classes: Set[Type[BaseAgent]] = set()
    
    async def discover_agents(self, force_rescan: bool = False) -> Dict[str, List[str]]:
        """
        Discover and register agents from configured scan paths.
        
        Args:
            force_rescan: Force rescan even if recently scanned
            
        Returns:
            Dictionary mapping module paths to discovered agent names
        """
        with tracer.start_as_current_span("agent_discovery.discover_agents") as span:
            span.set_attribute("force_rescan", force_rescan)
            
            # Check if scan is needed
            if not force_rescan and self._last_scan:
                time_since_scan = (datetime.utcnow() - self._last_scan).total_seconds()
                if time_since_scan < 5.0:  # Avoid too frequent scans
                    logger.debug("Skipping discovery - recently scanned")
                    return self._module_agents
            
            discovered_agents = {}
            scan_paths = self._get_scan_paths()
            
            span.set_attribute("scan_paths_count", len(scan_paths))
            
            logger.info(
                "Starting agent discovery",
                scan_paths=scan_paths,
                force_rescan=force_rescan
            )
            
            for scan_path in scan_paths:
                try:
                    agents = await self._scan_path(scan_path)
                    discovered_agents[scan_path] = agents
                    
                    logger.debug(
                        "Scanned path for agents",
                        scan_path=scan_path,
                        agents_found=len(agents)
                    )
                    
                except Exception as e:
                    logger.error(
                        "Failed to scan path for agents",
                        scan_path=scan_path,
                        error=str(e)
                    )
                    self._scan_errors[scan_path] = str(e)
            
            # Update discovery state
            self._last_scan = datetime.utcnow()
            self._module_agents.update(discovered_agents)
            
            total_discovered = sum(len(agents) for agents in discovered_agents.values())
            span.set_attribute("agents_discovered", total_discovered)
            
            logger.info(
                "Agent discovery completed",
                total_discovered=total_discovered,
                modules_scanned=len(discovered_agents),
                scan_errors=len(self._scan_errors)
            )
            
            return discovered_agents
    
    async def load_agent_module(self, module_path: str) -> List[Type[BaseAgent]]:
        """
        Load and inspect a specific module for agents.
        
        Args:
            module_path: Python module path (e.g., 'agents.keyword_research')
            
        Returns:
            List of discovered agent classes
        """
        with tracer.start_as_current_span("agent_discovery.load_module") as span:
            span.set_attribute("module_path", module_path)
            
            try:
                # Import or reload module
                if module_path in sys.modules:
                    module = importlib.reload(sys.modules[module_path])
                else:
                    module = importlib.import_module(module_path)
                
                # Find agent classes in module
                agent_classes = []
                for name, obj in inspect.getmembers(module):
                    if (inspect.isclass(obj) and 
                        issubclass(obj, BaseAgent) and 
                        obj != BaseAgent):
                        
                        agent_classes.append(obj)
                        self._loaded_agent_classes.add(obj)
                
                # Track module modification time for hot-reload
                if hasattr(module, '__file__') and module.__file__:
                    try:
                        mtime = os.path.getmtime(module.__file__)
                        self._module_mtimes[module_path] = mtime
                    except (OSError, AttributeError):
                        pass
                
                span.set_attribute("agent_classes_found", len(agent_classes))
                
                logger.debug(
                    "Loaded agent module",
                    module_path=module_path,
                    agent_classes=[cls.__name__ for cls in agent_classes]
                )
                
                return agent_classes
                
            except Exception as e:
                span.set_attribute("error", str(e))
                logger.error(
                    "Failed to load agent module",
                    module_path=module_path,
                    error=str(e)
                )
                
                raise AgentLoadingError(
                    f"Failed to load agent module '{module_path}': {str(e)}",
                    context={"module_path": module_path},
                    cause=e
                )
    
    async def reload_changed_modules(self) -> Dict[str, List[str]]:
        """
        Reload modules that have been modified (hot-reload).
        
        Returns:
            Dictionary mapping reloaded modules to agent names
        """
        with tracer.start_as_current_span("agent_discovery.reload_changed") as span:
            reloaded_modules = {}
            
            for module_path, old_mtime in self._module_mtimes.items():
                try:
                    if module_path not in sys.modules:
                        continue
                    
                    module = sys.modules[module_path]
                    if not hasattr(module, '__file__') or not module.__file__:
                        continue
                    
                    current_mtime = os.path.getmtime(module.__file__)
                    
                    if current_mtime > old_mtime:
                        logger.info(
                            "Module changed, reloading",
                            module_path=module_path,
                            old_mtime=old_mtime,
                            new_mtime=current_mtime
                        )
                        
                        # Unregister existing agents from this module
                        await self._unregister_module_agents(module_path)
                        
                        # Reload module and discover agents
                        agent_classes = await self.load_agent_module(module_path)
                        agent_names = [cls.__name__ for cls in agent_classes]
                        
                        reloaded_modules[module_path] = agent_names
                        
                        # Update modification time
                        self._module_mtimes[module_path] = current_mtime
                        
                except (OSError, AttributeError) as e:
                    logger.warning(
                        "Failed to check module modification time",
                        module_path=module_path,
                        error=str(e)
                    )
                except Exception as e:
                    logger.error(
                        "Failed to reload changed module",
                        module_path=module_path,
                        error=str(e)
                    )
            
            span.set_attribute("modules_reloaded", len(reloaded_modules))
            
            if reloaded_modules:
                logger.info(
                    "Hot-reload completed",
                    modules_reloaded=list(reloaded_modules.keys())
                )
            
            return reloaded_modules
    
    async def start_auto_reload(self) -> None:
        """Start automatic module reloading task."""
        if not self.config.auto_reload:
            logger.debug("Auto-reload disabled")
            return
        
        if self._auto_reload_task and not self._auto_reload_task.done():
            logger.debug("Auto-reload already running")
            return
        
        logger.info(
            "Starting auto-reload task",
            interval_seconds=self.config.reload_interval_seconds
        )
        
        self._auto_reload_task = asyncio.create_task(self._auto_reload_loop())
    
    async def stop_auto_reload(self) -> None:
        """Stop automatic module reloading task."""
        if self._auto_reload_task:
            self._auto_reload_task.cancel()
            try:
                await self._auto_reload_task
            except asyncio.CancelledError:
                pass
            
            self._auto_reload_task = None
            logger.info("Auto-reload task stopped")
    
    def get_discovery_stats(self) -> Dict[str, Any]:
        """
        Get discovery system statistics.
        
        Returns:
            Dictionary containing discovery statistics
        """
        return {
            "last_scan": self._last_scan.isoformat() if self._last_scan else None,
            "discovered_modules": len(self._discovered_modules),
            "loaded_agent_classes": len(self._loaded_agent_classes),
            "scan_errors": len(self._scan_errors),
            "auto_reload_enabled": self.config.auto_reload,
            "auto_reload_running": (
                self._auto_reload_task and not self._auto_reload_task.done()
            ) if self._auto_reload_task else False,
            "scan_paths": self._get_scan_paths(),
            "exclude_patterns": self.config.exclude_patterns
        }
    
    async def _scan_path(self, scan_path: str) -> List[str]:
        """Scan a specific path for agent modules."""
        discovered_agents = []
        
        if os.path.isfile(scan_path) and scan_path.endswith('.py'):
            # Single Python file
            module_path = self._file_to_module_path(scan_path)
            if module_path and not self._should_exclude(scan_path):
                try:
                    agent_classes = await self.load_agent_module(module_path)
                    discovered_agents.extend([cls.__name__ for cls in agent_classes])
                except Exception as e:
                    logger.warning(
                        "Failed to load agent from file",
                        file_path=scan_path,
                        error=str(e)
                    )
        
        elif os.path.isdir(scan_path):
            # Directory - scan recursively
            for root, dirs, files in os.walk(scan_path):
                # Apply depth limit
                depth = len(Path(root).relative_to(Path(scan_path)).parts)
                if depth >= self.config.max_scan_depth:
                    dirs.clear()  # Don't descend further
                    continue
                
                # Filter out excluded directories
                dirs[:] = [d for d in dirs if not self._should_exclude(os.path.join(root, d))]
                
                # Process Python files
                for file in files:
                    if file.endswith('.py') and file != '__init__.py':
                        file_path = os.path.join(root, file)
                        
                        if self._should_exclude(file_path):
                            continue
                        
                        module_path = self._file_to_module_path(file_path)
                        if module_path:
                            try:
                                agent_classes = await self.load_agent_module(module_path)
                                discovered_agents.extend([cls.__name__ for cls in agent_classes])
                                
                                # Track discovered module
                                self._discovered_modules[module_path] = datetime.utcnow()
                                
                            except Exception as e:
                                logger.warning(
                                    "Failed to load agent from file",
                                    file_path=file_path,
                                    module_path=module_path,
                                    error=str(e)
                                )
        
        return discovered_agents
    
    def _get_scan_paths(self) -> List[str]:
        """Get list of paths to scan for agents."""
        if self.config.scan_paths:
            return self.config.scan_paths
        
        # Default: scan current agents package
        agents_package = sys.modules.get('agents')
        if agents_package and hasattr(agents_package, '__path__'):
            return list(agents_package.__path__)
        
        # Fallback: scan current package directory
        current_dir = os.path.dirname(os.path.abspath(__file__))
        return [current_dir]
    
    def _should_exclude(self, path: str) -> bool:
        """Check if path should be excluded from scanning."""
        import fnmatch
        
        path_str = str(path)
        
        for pattern in self.config.exclude_patterns:
            if fnmatch.fnmatch(os.path.basename(path_str), pattern):
                return True
            
            if fnmatch.fnmatch(path_str, pattern):
                return True
        
        return False
    
    def _file_to_module_path(self, file_path: str) -> Optional[str]:
        """Convert file path to Python module path."""
        try:
            # Get absolute path
            abs_path = os.path.abspath(file_path)
            
            # Remove .py extension
            if abs_path.endswith('.py'):
                abs_path = abs_path[:-3]
            
            # Find the module path relative to Python path
            for sys_path in sys.path:
                sys_path_abs = os.path.abspath(sys_path)
                if abs_path.startswith(sys_path_abs):
                    rel_path = os.path.relpath(abs_path, sys_path_abs)
                    module_path = rel_path.replace(os.path.sep, '.')
                    
                    # Clean up module path
                    while module_path.startswith('.'):
                        module_path = module_path[1:]
                    
                    return module_path
            
            return None
            
        except Exception as e:
            logger.debug(
                "Failed to convert file path to module path",
                file_path=file_path,
                error=str(e)
            )
            return None
    
    async def _unregister_module_agents(self, module_path: str) -> None:
        """Unregister all agents from a specific module."""
        # Find agents registered from this module
        agents_to_remove = []
        
        for agent_name, metadata in self.registry._agents.items():
            if metadata.module_path and metadata.module_path.startswith(module_path):
                agents_to_remove.append(agent_name)
        
        # Unregister found agents
        for agent_name in agents_to_remove:
            await self.registry.unregister_agent(agent_name)
            logger.debug(
                "Unregistered agent for module reload",
                agent_name=agent_name,
                module_path=module_path
            )
    
    async def _auto_reload_loop(self) -> None:
        """Auto-reload loop task."""
        logger.info("Auto-reload loop started")
        
        try:
            while True:
                await asyncio.sleep(self.config.reload_interval_seconds)
                
                try:
                    reloaded = await self.reload_changed_modules()
                    
                    if reloaded:
                        logger.info(
                            "Auto-reload detected changes",
                            reloaded_modules=list(reloaded.keys())
                        )
                        
                except Exception as e:
                    logger.error(
                        "Auto-reload check failed",
                        error=str(e)
                    )
                    
        except asyncio.CancelledError:
            logger.info("Auto-reload loop cancelled")
            raise


# Global discovery system instance
_global_discovery_system = None


def get_agent_discovery_system(
    config: Optional[AgentDiscoveryConfig] = None
) -> AgentDiscoverySystem:
    """Get the global agent discovery system instance."""
    global _global_discovery_system
    
    if _global_discovery_system is None:
        _global_discovery_system = AgentDiscoverySystem(config=config)
    
    return _global_discovery_system


async def discover_agents(force_rescan: bool = False) -> Dict[str, List[str]]:
    """
    Convenience function for agent discovery using global system.
    
    Args:
        force_rescan: Force rescan even if recently scanned
        
    Returns:
        Dictionary mapping module paths to discovered agent names
    """
    discovery_system = get_agent_discovery_system()
    return await discovery_system.discover_agents(force_rescan=force_rescan)


async def reload_changed_agents() -> Dict[str, List[str]]:
    """
    Convenience function for hot-reloading changed agent modules.
    
    Returns:
        Dictionary mapping reloaded modules to agent names
    """
    discovery_system = get_agent_discovery_system()
    return await discovery_system.reload_changed_modules()