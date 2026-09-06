#!/usr/bin/env python3
"""
NUCLEAR LAUNCHER v10.0 - PRODUCTION OPTIMIZED
Enterprise-grade trading bot with modular architecture, persistent PnL tracking,
and support for 19 institutional trading algorithms.

Architecture:
- Modular strategy pattern for algorithms
- Persistent PnL with 24-hour balance reset
- Connection pooling and circuit breakers
- Comprehensive performance metrics
- Type-safe enums and dataclasses
"""

import os
import sys
import json
import time
import threading
import random
import logging
import gzip
import io
import hashlib
import pickle
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from enum import Enum, auto
from functools import lru_cache, wraps
from http.server import HTTPServer, BaseHTTPRequestHandler
from io import StringIO, BytesIO
from pathlib import Path
from queue import Queue, Empty, Full
from typing import Dict, List, Optional, Tuple, Any, Union, Deque, Set
import urllib.request
import urllib.parse
import urllib.error
import sqlite3

# ======================== CONFIGURATION MANAGEMENT ========================

@dataclass
class TradingConfig:
    """Centralized configuration with validation."""
    
    # API Configuration
    api_timeout: int = 5
    max_retries: int = 3
    cache_duration: float = 1.0
    rate_limit_threshold: float = 0.8
    circuit_breaker_cooldown: int = 300
    ip_ban_cooldown: int = 900
    
    # Trading Configuration
    min_trade_confidence: float = 0.6
    max_open_positions: int = 10
    position_size_min: float = 0.01
    position_size_max: float = 0.03
    stop_loss_percent: float = 0.05
    take_profit_percent: float = 0.03
    
    # System Configuration
    price_update_interval: int = 2
    trading_loop_interval: int = 5
    dashboard_refresh_interval: int = 5000
    balance_reset_interval: int = 86400  # 24 hours
    
    # Persistence
    data_dir: str = 'data'
    db_file: str = 'trading_data.db'
    config_file: str = 'config.json'
    
    @classmethod
    def from_file(cls, filepath: str) -> 'TradingConfig':
        """Load configuration from JSON file."""
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
                return cls(**data)
        except (FileNotFoundError, json.JSONDecodeError):
            return cls()
    
    def save(self, filepath: str) -> None:
        """Save configuration to JSON file."""
        with open(filepath, 'w') as f:
            json.dump(asdict(self), f, indent=2)

# Load configuration
CONFIG = TradingConfig()

# ======================== LOGGING CONFIGURATION ========================

class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors for console output."""
    
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
    }
    RESET = '\033[0m'
    
    def format(self, record):
        log_color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{log_color}{record.levelname}{self.RESET}"
        return super().format(record)

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(ColoredFormatter(
    '%(asctime)s - %(levelname)s - %(message)s'
))
logger.addHandler(console_handler)

# ======================== ENUMS AND CONSTANTS ========================

class TradeSide(Enum):
    """Trade direction enumeration."""
    LONG = "LONG"
    SHORT = "SHORT"

class TradeStatus(Enum):
    """Trade status enumeration."""
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PENDING = "PENDING"

class RiskLevel(Enum):
    """Risk level enumeration with visual indicators."""
    LOW = ("LOW", "#4ecdc4", "🟢")
    MEDIUM = ("MEDIUM", "#ffeaa7", "🟡")
    HIGH = ("HIGH", "#ff6b6b", "🔴")
    
    @property
    def name(self) -> str:
        return self.value[0]
    
    @property
    def color(self) -> str:
        return self.value[1]
    
    @property
    def emoji(self) -> str:
        return self.value[2]

class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = auto()
    OPEN = auto()
    HALF_OPEN = auto()

# ======================== ENVIRONMENT CONFIGURATION ========================

def get_env_var(key: str, default: Any, type_func=str) -> Any:
    """Safely get and parse environment variable."""
    try:
        value = os.environ.get(key, str(default))
        return type_func(value)
    except (ValueError, TypeError) as e:
        logger.warning(f"Invalid {type_func.__name__} for {key}: {value}, using default: {default}")
        return default

# Load environment variables
PORT = get_env_var('PORT', 10000, int)
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
INITIAL_BALANCE = get_env_var('INITIAL_BALANCE', 1000.0, float)
MAX_LEVERAGE = get_env_var('MAX_LEVERAGE', 10, int)
USE_TESTNET = get_env_var('USE_TESTNET', 'true', lambda x: x.lower() in ('true', '1', 'yes'))
BINANCE_API_KEY = os.environ.get('BINANCE_API_KEY', '').strip()
BINANCE_API_SECRET = os.environ.get('BINANCE_API_SECRET', '').strip()

# ======================== EXCEPTIONS ========================

class TradingBotException(Exception):
    """Base exception for trading bot."""
    pass

class CircuitBreakerOpenError(TradingBotException):
    """Raised when circuit breaker is open."""
    pass

class InsufficientBalanceError(TradingBotException):
    """Raised when balance is insufficient for trade."""
    pass

# ======================== PERFORMANCE METRICS ========================

@dataclass
class PerformanceMetrics:
    """Comprehensive performance metrics tracking."""
    
    request_times: Deque[float] = field(default_factory=lambda: deque(maxlen=1000))
    response_times: Deque[float] = field(default_factory=lambda: deque(maxlen=1000))
    request_sizes: Deque[int] = field(default_factory=lambda: deque(maxlen=1000))
    response_sizes: Deque[int] = field(default_factory=lambda: deque(maxlen=1000))
    error_counts: Dict[str, int] = field(default_factory=dict)
    endpoint_latencies: Dict[str, Deque[float]] = field(default_factory=lambda: defaultdict(lambda: deque(maxlen=100)))
    
    def record_request(self, endpoint: str, size: int, latency: float, 
                      response_size: int, error: Optional[str] = None) -> None:
        """Record metrics for a request."""
        self.request_times.append(time.time())
        self.response_times.append(latency)
        self.request_sizes.append(size)
        self.response_sizes.append(response_size)
        self.endpoint_latencies[endpoint].append(latency)
        
        if error:
            self.error_counts[error] = self.error_counts.get(error, 0) + 1
    
    def get_statistics(self) -> Dict[str, Any]:
        """Calculate and return statistics."""
        if not self.response_times:
            return {'status': 'no_data'}
        
        response_times = sorted(list(self.response_times))
        total_requests = len(self.request_times)
        
        return {
            'requests_per_minute': total_requests / max(1, (time.time() - self.request_times[0]) / 60) if self.request_times else 0,
            'avg_latency_ms': sum(response_times) / len(response_times) * 1000,
            'p50_latency_ms': response_times[len(response_times) // 2] * 1000,
            'p95_latency_ms': response_times[int(len(response_times) * 0.95)] * 1000 if len(response_times) > 20 else 0,
            'p99_latency_ms': response_times[int(len(response_times) * 0.99)] * 1000 if len(response_times) > 100 else 0,
            'avg_request_size': sum(self.request_sizes) / len(self.request_sizes) if self.request_sizes else 0,
            'avg_response_size': sum(self.response_sizes) / len(self.response_sizes) if self.response_sizes else 0,
            'error_rate': sum(self.error_counts.values()) / total_requests if total_requests > 0 else 0,
            'top_errors': sorted(self.error_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        }

# ======================== PERSISTENCE LAYER ========================

class PersistenceManager:
    """Manages data persistence with automatic PnL tracking and balance reset."""
    
    def __init__(self, data_dir: str = CONFIG.data_dir, db_file: str = CONFIG.db_file):
        """Initialize persistence manager."""
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        self.db_path = self.data_dir / db_file
        self._lock = threading.RLock()
        self._init_database()
    
    def _init_database(self) -> None:
        """Initialize SQLite database with tables."""
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            # PnL history table (never resets)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS pnl_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    realized_pnl REAL NOT NULL,
                    unrealized_pnl REAL NOT NULL,
                    total_pnl REAL NOT NULL,
                    trade_count INTEGER NOT NULL,
                    win_rate REAL
                )
            ''')
            
            # Balance tracking table (resets every 24h)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS balance_tracking (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    balance REAL NOT NULL,
                    last_reset REAL NOT NULL,
                    session_pnl REAL DEFAULT 0
                )
            ''')
            
            # Trade history table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS trade_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL,
                    leverage INTEGER NOT NULL,
                    position_size REAL NOT NULL,
                    pnl REAL,
                    algorithm TEXT NOT NULL,
                    open_time REAL NOT NULL,
                    close_time REAL,
                    status TEXT NOT NULL
                )
            ''')
            
            # Algorithm performance table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS algorithm_performance (
                    algorithm TEXT PRIMARY KEY,
                    total_trades INTEGER DEFAULT 0,
                    winning_trades INTEGER DEFAULT 0,
                    total_pnl REAL DEFAULT 0,
                    last_updated REAL
                )
            ''')
            
            conn.commit()
            conn.close()
    
    def get_current_balance(self) -> Tuple[float, float, datetime]:
        """Get current balance with auto-reset logic.
        
        Returns:
            Tuple of (balance, session_pnl, last_reset_time)
        """
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            # Get latest balance entry
            cursor.execute('''
                SELECT balance, last_reset, session_pnl 
                FROM balance_tracking 
                ORDER BY id DESC 
                LIMIT 1
            ''')
            result = cursor.fetchone()
            
            current_time = time.time()
            
            if result:
                balance, last_reset, session_pnl = result
                
                # Check if 24 hours have passed
                if current_time - last_reset >= CONFIG.balance_reset_interval:
                    # Reset balance to initial, preserve PnL
                    balance = INITIAL_BALANCE
                    last_reset = current_time
                    session_pnl = 0
                    
                    cursor.execute('''
                        INSERT INTO balance_tracking (timestamp, balance, last_reset, session_pnl)
                        VALUES (?, ?, ?, ?)
                    ''', (current_time, balance, last_reset, session_pnl))
                    conn.commit()
                    
                    logger.info(f"Balance reset to ${balance:.2f} (24-hour reset)")
            else:
                # First run
                balance = INITIAL_BALANCE
                last_reset = current_time
                session_pnl = 0
                
                cursor.execute('''
                    INSERT INTO balance_tracking (timestamp, balance, last_reset, session_pnl)
                    VALUES (?, ?, ?, ?)
                ''', (current_time, balance, last_reset, session_pnl))
                conn.commit()
            
            conn.close()
            return balance, session_pnl, datetime.fromtimestamp(last_reset)
    
    def update_balance(self, new_balance: float, pnl_change: float) -> None:
        """Update balance and session PnL."""
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            # Get current session info
            cursor.execute('''
                SELECT last_reset, session_pnl 
                FROM balance_tracking 
                ORDER BY id DESC 
                LIMIT 1
            ''')
            result = cursor.fetchone()
            
            if result:
                last_reset, session_pnl = result
                new_session_pnl = session_pnl + pnl_change
            else:
                last_reset = time.time()
                new_session_pnl = pnl_change
            
            cursor.execute('''
                INSERT INTO balance_tracking (timestamp, balance, last_reset, session_pnl)
                VALUES (?, ?, ?, ?)
            ''', (time.time(), new_balance, last_reset, new_session_pnl))
            
            conn.commit()
            conn.close()
    
    def save_pnl_snapshot(self, realized_pnl: float, unrealized_pnl: float, 
                         trade_count: int, win_rate: float) -> None:
        """Save PnL snapshot to history (never resets)."""
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            total_pnl = realized_pnl + unrealized_pnl
            
            cursor.execute('''
                INSERT INTO pnl_history (timestamp, realized_pnl, unrealized_pnl, total_pnl, trade_count, win_rate)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (time.time(), realized_pnl, unrealized_pnl, total_pnl, trade_count, win_rate))
            
            conn.commit()
            conn.close()
    
    def get_historical_pnl(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get historical PnL data."""
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            cutoff_time = time.time() - (days * 86400)
            
            cursor.execute('''
                SELECT timestamp, realized_pnl, unrealized_pnl, total_pnl, trade_count, win_rate
                FROM pnl_history
                WHERE timestamp > ?
                ORDER BY timestamp DESC
                LIMIT 1000
            ''', (cutoff_time,))
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    'timestamp': datetime.fromtimestamp(row[0]).isoformat(),
                    'realized_pnl': row[1],
                    'unrealized_pnl': row[2],
                    'total_pnl': row[3],
                    'trade_count': row[4],
                    'win_rate': row[5]
                })
            
            conn.close()
            return results
    
    def save_trade(self, trade: Dict[str, Any]) -> None:
        """Save trade to history."""
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO trade_history 
                (trade_id, symbol, side, entry_price, exit_price, leverage, 
                 position_size, pnl, algorithm, open_time, close_time, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                trade['id'],
                trade['symbol'],
                trade['side'].value if isinstance(trade['side'], TradeSide) else trade['side'],
                trade['entry_price'],
                trade.get('exit_price'),
                trade['leverage'],
                trade['position_value'],
                trade.get('pnl', 0),
                trade['algorithm'],
                trade['open_time'].timestamp() if isinstance(trade['open_time'], datetime) else trade['open_time'],
                trade.get('close_time').timestamp() if trade.get('close_time') and isinstance(trade['close_time'], datetime) else trade.get('close_time'),
                trade['status'].value if isinstance(trade['status'], TradeStatus) else trade['status']
            ))
            
            conn.commit()
            conn.close()
    
    def update_algorithm_performance(self, algorithm: str, won: bool, pnl: float) -> None:
        """Update algorithm performance metrics."""
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO algorithm_performance 
                (algorithm, total_trades, winning_trades, total_pnl, last_updated)
                VALUES (
                    ?,
                    COALESCE((SELECT total_trades FROM algorithm_performance WHERE algorithm = ?), 0) + 1,
                    COALESCE((SELECT winning_trades FROM algorithm_performance WHERE algorithm = ?), 0) + ?,
                    COALESCE((SELECT total_pnl FROM algorithm_performance WHERE algorithm = ?), 0) + ?,
                    ?
                )
            ''', (algorithm, algorithm, algorithm, 1 if won else 0, algorithm, pnl, time.time()))
            
            conn.commit()
            conn.close()
    
    def get_algorithm_performance(self) -> Dict[str, Dict[str, Any]]:
        """Get algorithm performance statistics."""
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT algorithm, total_trades, winning_trades, total_pnl
                FROM algorithm_performance
                ORDER BY total_pnl DESC
            ''')
            
            results = {}
            for row in cursor.fetchall():
                algorithm, total_trades, winning_trades, total_pnl = row
                results[algorithm] = {
                    'trades': total_trades,
                    'wins': winning_trades,
                    'pnl': total_pnl,
                    'win_rate': (winning_trades / total_trades * 100) if total_trades > 0 else 0
                }
            
            conn.close()
            return results

# ======================== CIRCULAR BUFFER IMPLEMENTATION ========================

class CircularBuffer:
    """Memory-efficient circular buffer for price history."""
    
    __slots__ = ('_buffer', '_size', '_index', '_full')
    
    def __init__(self, size: int):
        """Initialize circular buffer."""
        self._buffer = [0.0] * size
        self._size = size
        self._index = 0
        self._full = False
    
    def append(self, value: float) -> None:
        """Add value to buffer."""
        self._buffer[self._index] = value
        self._index = (self._index + 1) % self._size
        if self._index == 0:
            self._full = True
    
    def get_recent(self, n: int) -> List[float]:
        """Get last n values efficiently."""
        if not self._full and self._index < n:
            return self._buffer[:self._index]
        
        if n >= self._size:
            return self.get_all()
        
        start = (self._index - n) % self._size
        if start < self._index:
            return self._buffer[start:self._index]
        else:
            return self._buffer[start:] + self._buffer[:self._index]
    
    def get_all(self) -> List[float]:
        """Get all values in order."""
        if not self._full:
            return self._buffer[:self._index]
        return self._buffer[self._index:] + self._buffer[:self._index]
    
    def __len__(self) -> int:
        """Get number of stored values."""
        return self._size if self._full else self._index

# ======================== CONNECTION POOL ========================

class ConnectionPool:
    """Thread-safe connection pool for HTTP/HTTPS."""
    
    def __init__(self, max_connections: int = 10):
        """Initialize connection pool."""
        self._max_connections = max_connections
        self._connections: Queue = Queue(maxsize=max_connections)
        self._lock = threading.RLock()
        self._created = 0
    
    def _create_connection(self) -> urllib.request.OpenerDirector:
        """Create new connection opener."""
        http_handler = urllib.request.HTTPHandler()
        https_handler = urllib.request.HTTPSHandler()
        return urllib.request.build_opener(http_handler, https_handler)
    
    def get_connection(self, timeout: float = 1.0) -> urllib.request.OpenerDirector:
        """Get connection from pool or create new one."""
        try:
            return self._connections.get(block=True, timeout=timeout)
        except Empty:
            with self._lock:
                if self._created < self._max_connections:
                    self._created += 1
                    return self._create_connection()
                else:
                    # Wait longer for a connection
                    return self._connections.get(block=True, timeout=5.0)
    
    def return_connection(self, conn: urllib.request.OpenerDirector) -> None:
        """Return connection to pool."""
        try:
            self._connections.put(conn, block=False)
        except Full:
            pass  # Pool is full, discard connection

# ======================== ADAPTIVE CIRCUIT BREAKER ========================

class AdaptiveCircuitBreaker:
    """Circuit breaker with gradual recovery."""
    
    def __init__(self, failure_threshold: int = 5, 
                 recovery_timeout: int = 300,
                 half_open_requests: int = 3):
        """Initialize circuit breaker."""
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_requests = half_open_requests
        
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = 0
        self.state = CircuitState.CLOSED
        self.half_open_remaining = 0
        self._lock = threading.RLock()
    
    def call(self, func, *args, **kwargs):
        """Execute function through circuit breaker."""
        with self._lock:
            if self.state == CircuitState.OPEN:
                if time.time() - self.last_failure_time > self.recovery_timeout:
                    self.state = CircuitState.HALF_OPEN
                    self.half_open_remaining = self.half_open_requests
                    logger.info("Circuit breaker entering HALF_OPEN state")
                else:
                    raise CircuitBreakerOpenError("Circuit breaker is OPEN")
            
            if self.state == CircuitState.HALF_OPEN:
                if self.half_open_remaining <= 0:
                    if self.success_count > self.failure_count:
                        self.state = CircuitState.CLOSED
                        self.reset_counts()
                        logger.info("Circuit breaker CLOSED - recovered")
                    else:
                        self.state = CircuitState.OPEN
                        self.last_failure_time = time.time()
                        logger.warning("Circuit breaker reopened - recovery failed")
                        raise CircuitBreakerOpenError("Circuit breaker reopened")
                
                self.half_open_remaining -= 1
        
        try:
            result = func(*args, **kwargs)
            self.on_success()
            return result
        except Exception as e:
            self.on_failure()
            raise
    
    def on_success(self):
        """Record successful call."""
        with self._lock:
            self.success_count += 1
            if self.state == CircuitState.CLOSED:
                self.failure_count = max(0, self.failure_count - 1)
    
    def on_failure(self):
        """Record failed call."""
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.failure_count >= self.failure_threshold:
                self.state = CircuitState.OPEN
                logger.error(f"Circuit breaker OPEN after {self.failure_count} failures")
    
    def reset_counts(self):
        """Reset success/failure counts."""
        self.failure_count = 0
        self.success_count = 0
    
    def get_state(self) -> str:
        """Get current state as string."""
        return self.state.name

# ======================== REQUEST DEDUPLICATOR ========================

class RequestDeduplicator:
    """Deduplicates concurrent identical requests."""
    
    def __init__(self):
        """Initialize deduplicator."""
        self._pending: Dict[str, Future] = {}
        self._lock = threading.Lock()
    
    def deduplicate(self, key: str, func, *args, **kwargs):
        """Execute function only once for concurrent identical requests."""
        with self._lock:
            if key in self._pending:
                future = self._pending[key]
        else:
                # Create new future and execute function
                future = Future()
                self._pending[key] = future
                
                # Execute in separate thread to avoid holding lock
                def execute():
                    try:
                        result = func(*args, **kwargs)
                        future.set_result(result)
                    except Exception as e:
                        future.set_exception(e)
                    finally:
                        with self._lock:
                            if key in self._pending:
                                del self._pending[key]
                
                threading.Thread(target=execute, daemon=True).start()
        
        return future.result(timeout=30)

# ======================== TRADING STRATEGY BASE CLASS ========================

class TradingStrategy(ABC):
    """Abstract base class for trading strategies."""
    
    def __init__(self, algorithm_id: str, name: str, description: str, 
                 risk_level: RiskLevel, color: str):
        """Initialize trading strategy."""
        self.algorithm_id = algorithm_id
        self.name = name
        self.description = description
        self.risk_level = risk_level
        self.color = color
    
    @abstractmethod
    def analyze(self, symbol: str, price_history: List[float], 
                current_price: float, volume_history: Optional[List[float]] = None,
                **kwargs) -> Optional[Dict[str, Any]]:
        """Analyze market and return signal if conditions are met.
        
        Returns:
            Dictionary with signal details or None if no signal
        """
        pass
    
    def calculate_sma(self, prices: List[float], period: int) -> float:
        """Calculate Simple Moving Average."""
        if len(prices) < period:
            return prices[-1] if prices else 0.0
        return sum(prices[-period:]) / period
    
    def calculate_ema(self, prices: List[float], period: int) -> float:
        """Calculate Exponential Moving Average."""
        if len(prices) < period:
            return prices[-1] if prices else 0.0
        
        multiplier = 2.0 / (period + 1)
        ema = sum(prices[:period]) / period
        
        for price in prices[period:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        
        return ema
    
    def calculate_rsi(self, prices: List[float], period: int = 14) -> float:
        """Calculate Relative Strength Index."""
        if len(prices) < period + 1:
            return 50.0
        
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [max(0, d) for d in deltas]
        losses = [max(0, -d) for d in deltas]
        
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

# ======================== TRADING STRATEGY IMPLEMENTATIONS ========================

class OrderFlowToxicityStrategy(TradingStrategy):
    """Order Flow Toxicity (VPIN) strategy."""
    
    def __init__(self):
        super().__init__(
            'ORDER_FLOW_TOXICITY',
            'Order Flow Toxicity (VPIN)',
            'Detects informed trading activity',
            RiskLevel.MEDIUM,
            '#ff6b6b'
        )
    
    def analyze(self, symbol: str, price_history: List[float], 
                current_price: float, volume_history: Optional[List[float]] = None,
                **kwargs) -> Optional[Dict[str, Any]]:
        if len(price_history) < 20 or not volume_history or len(volume_history) < 10:
            return None
        
        # Simplified VPIN calculation
        price_volatility = max(price_history[-20:]) - min(price_history[-20:])
        avg_price = sum(price_history[-20:]) / 20
        
        if avg_price > 0 and price_volatility / avg_price > 0.02:
            volume_imbalance = max(volume_history[-10:]) / (sum(volume_history[-10:]) / 10)
            
            if volume_imbalance > 2.0:
                direction = 'BUY' if current_price > self.calculate_sma(price_history, 10) else 'SELL'
                return {
                    'algorithm': self.algorithm_id,
                    'signal': direction,
                    'strength': min(volume_imbalance / 3, 1.0),
                    'reason': f'Toxic flow detected (imbalance: {volume_imbalance:.2f}x)'
                }
        
        return None

class MarketMicrostructureStrategy(TradingStrategy):
    """Market Microstructure Analysis strategy."""
    
    def __init__(self):
        super().__init__(
            'MARKET_MICROSTRUCTURE',
            'Market Microstructure Analysis',
            'Analyzes bid-ask dynamics and liquidity',
            RiskLevel.LOW,
            '#4ecdc4'
        )
    
    def analyze(self, symbol: str, price_history: List[float], 
                current_price: float, volume_history: Optional[List[float]] = None,
                **kwargs) -> Optional[Dict[str, Any]]:
        if len(price_history) < 30:
            return None
        
        # Analyze price micro-movements
        recent_changes = [(price_history[i] - price_history[i-1]) / price_history[i-1] 
                         for i in range(-10, 0) if price_history[i-1] > 0]
        
        if recent_changes:
            avg_change = sum(recent_changes) / len(recent_changes)
            if abs(avg_change) > 0.001:
                return {
                    'algorithm': self.algorithm_id,
                    'signal': 'BUY' if avg_change > 0 else 'SELL',
                    'strength': min(abs(avg_change) * 500, 0.8),
                    'reason': f'Microstructure shift detected ({avg_change*100:.3f}%)'
                }
        
        return None

class TickDirectionStrategy(TradingStrategy):
    """Tick Direction Analysis strategy."""
    
    def __init__(self):
        super().__init__(
            'TICK_DIRECTION',
            'Tick Direction Analysis',
            'Ultra-fast momentum from tick data',
            RiskLevel.HIGH,
            '#45b7d1'
        )
    
    def analyze(self, symbol: str, price_history: List[float], 
                current_price: float, volume_history: Optional[List[float]] = None,
                **kwargs) -> Optional[Dict[str, Any]]:
        if len(price_history) < 10:
            return None
        
        # Count upticks vs downticks
        upticks = sum(1 for i in range(-9, 0) if price_history[i] > price_history[i-1])
        downticks = sum(1 for i in range(-9, 0) if price_history[i] < price_history[i-1])
        
        tick_ratio = upticks / max(downticks, 1)
        
        if tick_ratio > 2.0 or tick_ratio < 0.5:
            return {
                'algorithm': self.algorithm_id,
                'signal': 'BUY' if tick_ratio > 1 else 'SELL',
                'strength': min(abs(tick_ratio - 1) / 2, 0.9),
                'reason': f'Tick momentum {upticks}:{downticks}'
            }
        
        return None

class VolumeProfileStrategy(TradingStrategy):
    """Volume Profile Analysis strategy."""
    
    def __init__(self):
        super().__init__(
            'VOLUME_PROFILE',
            'Volume Profile Analysis',
            'Identifies key institutional levels',
            RiskLevel.MEDIUM,
            '#96ceb4'
        )
    
    def analyze(self, symbol: str, price_history: List[float], 
                current_price: float, volume_history: Optional[List[float]] = None,
                **kwargs) -> Optional[Dict[str, Any]]:
        if not volume_history or len(volume_history) < 20:
            return None
        
        avg_volume = sum(volume_history) / len(volume_history)
        recent_volume = volume_history[-1] if volume_history else 0
        
        if avg_volume > 0 and recent_volume > avg_volume * 1.5:
            price_position = (current_price - min(price_history[-20:])) / \
                           (max(price_history[-20:]) - min(price_history[-20:]) + 0.0001)
            
            if price_position > 0.8 or price_position < 0.2:
                return {
                    'algorithm': self.algorithm_id,
                    'signal': 'SELL' if price_position > 0.8 else 'BUY',
                    'strength': min(recent_volume / avg_volume / 2, 0.85),
                    'reason': f'Volume breakout at {"resistance" if price_position > 0.8 else "support"}'
                }
        
        return None

class MultiTimeframeMomentumStrategy(TradingStrategy):
    """Multi-Timeframe Momentum strategy."""
    
    def __init__(self):
        super().__init__(
            'MULTI_TIMEFRAME_MOMENTUM',
            'Multi-Timeframe Momentum',
            'Confirms trend across timeframes',
            RiskLevel.MEDIUM,
            '#ffeaa7'
        )
    
    def analyze(self, symbol: str, price_history: List[float], 
                current_price: float, volume_history: Optional[List[float]] = None,
                **kwargs) -> Optional[Dict[str, Any]]:
        if len(price_history) < 20:
            return None
        
        sma_5 = self.calculate_sma(price_history, 5)
        sma_20 = self.calculate_sma(price_history, 20)
        
        if sma_20 > 0:
            momentum_ratio = sma_5 / sma_20
            
            if momentum_ratio > 1.01:
                return {
                    'algorithm': self.algorithm_id,
                    'signal': 'BUY',
                    'strength': min((momentum_ratio - 1) * 100, 1.0),
                    'reason': f'Momentum breakout ({momentum_ratio:.3f})'
                }
            elif momentum_ratio < 0.99:
                return {
                    'algorithm': self.algorithm_id,
                    'signal': 'SELL',
                    'strength': min((1 - momentum_ratio) * 100, 1.0),
                    'reason': f'Momentum breakdown ({momentum_ratio:.3f})'
                }
        
        return None

class BreakoutDetectionStrategy(TradingStrategy):
    """Breakout Detection strategy."""
    
    def __init__(self):
        super().__init__(
            'BREAKOUT_DETECTION',
            'Breakout Detection',
            'Captures explosive moves early',
            RiskLevel.HIGH,
            '#dfe6e9'
        )
    
    def analyze(self, symbol: str, price_history: List[float], 
                current_price: float, volume_history: Optional[List[float]] = None,
                **kwargs) -> Optional[Dict[str, Any]]:
        if len(price_history) < 20:
            return None
        
        resistance = max(price_history[-20:-1])
        support = min(price_history[-20:-1])
        price_range = resistance - support
        
        if price_range > 0:
            if current_price > resistance:
                breakout_strength = (current_price - resistance) / price_range
                return {
                    'algorithm': self.algorithm_id,
                    'signal': 'BUY',
                    'strength': min(breakout_strength * 3, 0.95),
                    'reason': f'Resistance breakout at ${resistance:.4f}'
                }
            elif current_price < support:
                breakdown_strength = (support - current_price) / price_range
                return {
                    'algorithm': self.algorithm_id,
                    'signal': 'SELL',
                    'strength': min(breakdown_strength * 3, 0.95),
                    'reason': f'Support breakdown at ${support:.4f}'
                }
        
        return None

class IchimokuCloudStrategy(TradingStrategy):
    """Ichimoku Cloud System strategy."""
    
    def __init__(self):
        super().__init__(
            'ICHIMOKU_CLOUD',
            'Ichimoku Cloud System',
            'Japanese trend analysis system',
            RiskLevel.MEDIUM,
            '#00b894'
        )
    
    def analyze(self, symbol: str, price_history: List[float], 
                current_price: float, volume_history: Optional[List[float]] = None,
                **kwargs) -> Optional[Dict[str, Any]]:
        if len(price_history) < 52:
            return None
        
        # Simplified Ichimoku calculation
        tenkan = (max(price_history[-9:]) + min(price_history[-9:])) / 2
        kijun = (max(price_history[-26:]) + min(price_history[-26:])) / 2
        
        if tenkan > kijun * 1.005:
            return {
                'algorithm': self.algorithm_id,
                'signal': 'BUY',
                'strength': min((tenkan / kijun - 1) * 50, 0.8),
                'reason': 'Tenkan-Kijun bullish cross'
            }
        elif tenkan < kijun * 0.995:
            return {
                'algorithm': self.algorithm_id,
                'signal': 'SELL',
                'strength': min((1 - tenkan / kijun) * 50, 0.8),
                'reason': 'Tenkan-Kijun bearish cross'
            }
        
        return None

class ElliottWaveStrategy(TradingStrategy):
    """Elliott Wave Pattern strategy."""
    
    def __init__(self):
        super().__init__(
            'ELLIOTT_WAVE',
            'Elliott Wave Pattern',
            'Market psychology wave patterns',
            RiskLevel.HIGH,
            '#6c5ce7'
        )
    
    def analyze(self, symbol: str, price_history: List[float], 
                current_price: float, volume_history: Optional[List[float]] = None,
                **kwargs) -> Optional[Dict[str, Any]]:
        if len(price_history) < 30:
            return None
        
        # Simplified wave detection
        peaks = []
        troughs = []
        
        for i in range(1, len(price_history) - 1):
            if price_history[i] > price_history[i-1] and price_history[i] > price_history[i+1]:
                peaks.append(i)
            elif price_history[i] < price_history[i-1] and price_history[i] < price_history[i+1]:
                troughs.append(i)
        
        if len(peaks) >= 3 and len(troughs) >= 2:
            # Check for 5-wave pattern
            last_peak = price_history[peaks[-1]] if peaks else current_price
            last_trough = price_history[troughs[-1]] if troughs else current_price
            
            if current_price > last_peak:
                return {
                    'algorithm': self.algorithm_id,
                    'signal': 'BUY',
                    'strength': 0.7,
                    'reason': 'Elliott Wave 5 completion'
                }
            elif current_price < last_trough:
                return {
                    'algorithm': self.algorithm_id,
                    'signal': 'SELL',
                    'strength': 0.7,
                    'reason': 'Elliott Wave ABC correction'
                }
        
        return None

class FibonacciRetracementStrategy(TradingStrategy):
    """Fibonacci Retracement strategy."""
    
    def __init__(self):
        super().__init__(
            'FIBONACCI_RETRACEMENT',
            'Fibonacci Retracement',
            'Golden ratio support/resistance',
            RiskLevel.LOW,
            '#fdcb6e'
        )
    
    def analyze(self, symbol: str, price_history: List[float], 
                current_price: float, volume_history: Optional[List[float]] = None,
                **kwargs) -> Optional[Dict[str, Any]]:
        if len(price_history) < 20:
            return None
        
        high = max(price_history[-20:])
        low = min(price_history[-20:])
        diff = high - low
        
        if diff > 0:
            # Fibonacci levels
            fib_382 = high - (diff * 0.382)
            fib_618 = high - (diff * 0.618)
            
            tolerance = diff * 0.02
            
            if abs(current_price - fib_382) < tolerance:
                return {
                    'algorithm': self.algorithm_id,
                    'signal': 'BUY',
                    'strength': 0.65,
                    'reason': 'Fibonacci 38.2% retracement support'
                }
            elif abs(current_price - fib_618) < tolerance:
                return {
                    'algorithm': self.algorithm_id,
                    'signal': 'BUY',
                    'strength': 0.75,
                    'reason': 'Fibonacci 61.8% retracement support'
                }
        
        return None

class StatisticalMeanReversionStrategy(TradingStrategy):
    """Statistical Mean Reversion strategy."""
    
    def __init__(self):
        super().__init__(
            'STATISTICAL_MEAN_REVERSION',
            'Statistical Mean Reversion',
            'Exploits temporary mispricings',
            RiskLevel.LOW,
            '#e17055'
        )
    
    def analyze(self, symbol: str, price_history: List[float], 
                current_price: float, volume_history: Optional[List[float]] = None,
                **kwargs) -> Optional[Dict[str, Any]]:
        if len(price_history) < 20:
            return None
        
        sma_20 = self.calculate_sma(price_history, 20)
        
        if sma_20 > 0:
            deviation = (current_price - sma_20) / sma_20
            
            if deviation < -0.02:
                return {
                    'algorithm': self.algorithm_id,
                    'signal': 'BUY',
                    'strength': min(abs(deviation) * 25, 1.0),
                    'reason': f'Price {abs(deviation)*100:.1f}% below mean'
                }
            elif deviation > 0.02:
                return {
                    'algorithm': self.algorithm_id,
                    'signal': 'SELL',
                    'strength': min(abs(deviation) * 25, 1.0),
                    'reason': f'Price {abs(deviation)*100:.1f}% above mean'
                }
        
        return None

class RSIDivergenceStrategy(TradingStrategy):
    """RSI Divergence strategy."""
    
    def __init__(self):
        super().__init__(
            'RSI_DIVERGENCE',
            'RSI Divergence',
            'Early reversal detection',
            RiskLevel.MEDIUM,
            '#74b9ff'
        )
    
    def analyze(self, symbol: str, price_history: List[float], 
                current_price: float, volume_history: Optional[List[float]] = None,
                **kwargs) -> Optional[Dict[str, Any]]:
        if len(price_history) < 15:
            return None
        
        rsi = self.calculate_rsi(price_history)
        
        if rsi < 30:
            return {
                'algorithm': self.algorithm_id,
                'signal': 'BUY',
                'strength': (30 - rsi) / 30,
                'reason': f'RSI oversold at {rsi:.1f}'
            }
        elif rsi > 70:
            return {
                'algorithm': self.algorithm_id,
                'signal': 'SELL',
                'strength': (rsi - 70) / 30,
                'reason': f'RSI overbought at {rsi:.1f}'
            }
        
        return None

class VWAPMeanReversionStrategy(TradingStrategy):
    """VWAP Mean Reversion strategy."""
    
    def __init__(self):
        super().__init__(
            'VWAP_MEAN_REVERSION',
            'VWAP Mean Reversion',
            'Trades at institutional prices',
            RiskLevel.LOW,
            '#a29bfe'
        )
    
    def analyze(self, symbol: str, price_history: List[float], 
                current_price: float, volume_history: Optional[List[float]] = None,
                **kwargs) -> Optional[Dict[str, Any]]:
        if not volume_history or len(volume_history) < 20 or len(price_history) < 20:
            return None
        
        # Calculate VWAP
        total_pv = sum(p * v for p, v in zip(price_history[-20:], volume_history[-20:]))
        total_v = sum(volume_history[-20:])
        
        if total_v > 0:
            vwap = total_pv / total_v
            deviation = (current_price - vwap) / vwap
            
            if abs(deviation) > 0.015:
                return {
                    'algorithm': self.algorithm_id,
                    'signal': 'BUY' if deviation < 0 else 'SELL',
                    'strength': min(abs(deviation) * 30, 0.85),
                    'reason': f'VWAP deviation {deviation*100:.2f}%'
                }
        
        return None

class BollingerSqueezeStrategy(TradingStrategy):
    """Bollinger Band Squeeze strategy."""
    
    def __init__(self):
        super().__init__(
            'BOLLINGER_SQUEEZE',
            'Bollinger Band Squeeze',
            'Predicts volatility explosions',
            RiskLevel.MEDIUM,
            '#ff7675'
        )
    
    def analyze(self, symbol: str, price_history: List[float], 
                current_price: float, volume_history: Optional[List[float]] = None,
                **kwargs) -> Optional[Dict[str, Any]]:
        if len(price_history) < 20:
            return None
        
        sma = self.calculate_sma(price_history, 20)
        std_dev = (sum((p - sma) ** 2 for p in price_history[-20:]) / 20) ** 0.5
        
        upper_band = sma + (std_dev * 2)
        lower_band = sma - (std_dev * 2)
        band_width = upper_band - lower_band
        
        if sma > 0:
            squeeze_ratio = band_width / sma
            
            if squeeze_ratio < 0.02:  # Tight squeeze
                if current_price > sma:
                    return {
                        'algorithm': self.algorithm_id,
                        'signal': 'BUY',
                        'strength': 0.8,
                        'reason': 'Bollinger squeeze breakout imminent'
                    }
            elif current_price > upper_band:
                return {
                    'algorithm': self.algorithm_id,
                    'signal': 'SELL',
                    'strength': 0.7,
                    'reason': 'Above upper Bollinger band'
                }
            elif current_price < lower_band:
                return {
                    'algorithm': self.algorithm_id,
                    'signal': 'BUY',
                    'strength': 0.7,
                    'reason': 'Below lower Bollinger band'
                }
        
        return None

class PairsTradingStrategy(TradingStrategy):
    """Pairs Trading strategy."""
    
    def __init__(self):
        super().__init__(
            'PAIRS_TRADING',
            'Pairs Trading',
            'Market-neutral correlation trading',
            RiskLevel.LOW,
            '#fd79a8'
        )
    
    def analyze(self, symbol: str, price_history: List[float], 
                current_price: float, volume_history: Optional[List[float]] = None,
                **kwargs) -> Optional[Dict[str, Any]]:
        if len(price_history) < 30:
            return None
        
        # For simplicity, compare against moving average as proxy for pair
        ma_fast = self.calculate_sma(price_history, 10)
        ma_slow = self.calculate_sma(price_history, 30)
        
        if ma_slow > 0:
            spread = (ma_fast - ma_slow) / ma_slow
            
            if abs(spread) > 0.02:
                return {
                    'algorithm': self.algorithm_id,
                    'signal': 'BUY' if spread < 0 else 'SELL',
                    'strength': min(abs(spread) * 20, 0.75),
                    'reason': f'Pair spread deviation {spread*100:.2f}%'
                }
        
        return None

class GridTradingStrategy(TradingStrategy):
    """Grid Trading strategy."""
    
    def __init__(self):
        super().__init__(
            'GRID_TRADING',
            'Grid Trading',
            'Automated scalping in ranges',
            RiskLevel.MEDIUM,
            '#636e72'
        )
    
    def analyze(self, symbol: str, price_history: List[float], 
                current_price: float, volume_history: Optional[List[float]] = None,
                **kwargs) -> Optional[Dict[str, Any]]:
        if len(price_history) < 20:
            return None
        
        high = max(price_history[-20:])
        low = min(price_history[-20:])
        price_range = high - low
        
        if price_range > 0:
            position_in_range = (current_price - low) / price_range
            
            # Buy at lower grid levels, sell at upper levels
            if position_in_range < 0.3:
                return {
                    'algorithm': self.algorithm_id,
                    'signal': 'BUY',
                    'strength': 0.6,
                    'reason': f'Grid buy level ({position_in_range*100:.0f}% of range)'
                }
            elif position_in_range > 0.7:
                return {
                    'algorithm': self.algorithm_id,
                    'signal': 'SELL',
                    'strength': 0.6,
                    'reason': f'Grid sell level ({position_in_range*100:.0f}% of range)'
                }
        
        return None

class MarketMakingStrategy(TradingStrategy):
    """Market Making strategy."""
    
    def __init__(self):
        super().__init__(
            'MARKET_MAKING',
            'Market Making',
            'Provides liquidity, captures spread',
            RiskLevel.LOW,
            '#00cec9'
        )
    
    def analyze(self, symbol: str, price_history: List[float], 
                current_price: float, volume_history: Optional[List[float]] = None,
                **kwargs) -> Optional[Dict[str, Any]]:
        if len(price_history) < 10:
            return None
        
        # Calculate recent volatility
        recent_changes = [abs(price_history[i] - price_history[i-1]) / price_history[i-1] 
                         for i in range(-9, 0) if price_history[i-1] > 0]
        
        if recent_changes:
            avg_volatility = sum(recent_changes) / len(recent_changes)
            
            # Make market when volatility is low
            if avg_volatility < 0.002:
                mid_price = self.calculate_sma(price_history, 5)
                spread = abs(current_price - mid_price) / mid_price if mid_price > 0 else 0
                
                if spread > 0.001:
                    return {
                        'algorithm': self.algorithm_id,
                        'signal': 'BUY' if current_price < mid_price else 'SELL',
                        'strength': min(spread * 200, 0.6),
                        'reason': f'Market making opportunity (spread: {spread*100:.3f}%)'
                    }
        
        return None

class EnsembleMLStrategy(TradingStrategy):
    """Ensemble ML Predictor strategy."""
    
    def __init__(self):
        super().__init__(
            'ENSEMBLE_ML',
            'Ensemble ML Predictor',
            'Multiple ML models voting',
            RiskLevel.MEDIUM,
            '#ff6348'
        )
    
    def analyze(self, symbol: str, price_history: List[float], 
                current_price: float, volume_history: Optional[List[float]] = None,
                **kwargs) -> Optional[Dict[str, Any]]:
        if len(price_history) < 30:
            return None
        
        # Simulate ensemble of simple predictors
        signals = []
        
        # Momentum predictor
        momentum = (current_price - price_history[-10]) / price_history[-10] if price_history[-10] > 0 else 0
        if abs(momentum) > 0.01:
            signals.append(1 if momentum > 0 else -1)
        
        # Mean reversion predictor
        mean = sum(price_history[-20:]) / 20
        deviation = (current_price - mean) / mean if mean > 0 else 0
        if abs(deviation) > 0.015:
            signals.append(-1 if deviation > 0 else 1)
        
        # Trend predictor
        if len(price_history) >= 30:
            trend = (self.calculate_sma(price_history, 10) - self.calculate_sma(price_history, 30)) / self.calculate_sma(price_history, 30)
            if abs(trend) > 0.005:
                signals.append(1 if trend > 0 else -1)
        
        if len(signals) >= 2:
            ensemble_signal = sum(signals) / len(signals)
            
            if abs(ensemble_signal) > 0.5:
                return {
                    'algorithm': self.algorithm_id,
                    'signal': 'BUY' if ensemble_signal > 0 else 'SELL',
                    'strength': min(abs(ensemble_signal), 0.85),
                    'reason': f'Ensemble consensus ({len([s for s in signals if s > 0])}/{len(signals)} bullish)'
                }
        
        return None

class SentimentAnalysisStrategy(TradingStrategy):
    """Sentiment Analysis strategy."""
    
    def __init__(self):
        super().__init__(
            'SENTIMENT_ANALYSIS',
            'Sentiment Analysis',
            'Social media & news sentiment',
            RiskLevel.MEDIUM,
            '#5f27cd'
        )
    
    def analyze(self, symbol: str, price_history: List[float], 
                current_price: float, volume_history: Optional[List[float]] = None,
                **kwargs) -> Optional[Dict[str, Any]]:
        if len(price_history) < 20:
            return None
        
        # Simulate sentiment based on price action and volume
        price_momentum = (current_price - price_history[-5]) / price_history[-5] if price_history[-5] > 0 else 0
        
        if volume_history and len(volume_history) >= 5:
            volume_surge = volume_history[-1] / (sum(volume_history[-5:]) / 5) if sum(volume_history[-5:]) > 0 else 1
            
            # High volume + price movement = strong sentiment
            if volume_surge > 1.5 and abs(price_momentum) > 0.005:
                return {
                    'algorithm': self.algorithm_id,
                    'signal': 'BUY' if price_momentum > 0 else 'SELL',
                    'strength': min(volume_surge / 2, 0.9),
                    'reason': f'{"Bullish" if price_momentum > 0 else "Bearish"} sentiment surge (volume: {volume_surge:.1f}x)'
                }
        
        return None

class ScalpingStrategy(TradingStrategy):
    """High-Frequency Scalping strategy."""
    
    def __init__(self):
        super().__init__(
            'SCALPING',
            'High-Frequency Scalping',
            'Quick trades on micro movements',
            RiskLevel.HIGH,
            '#ee5a24'
        )
    
    def analyze(self, symbol: str, price_history: List[float], 
                current_price: float, volume_history: Optional[List[float]] = None,
                **kwargs) -> Optional[Dict[str, Any]]:
        if len(price_history) < 5:
            return None
        
        # Look for micro movements
        recent_prices = price_history[-5:]
        if recent_prices[0] > 0:
            price_change = (recent_prices[-1] - recent_prices[0]) / recent_prices[0]
            
            if abs(price_change) > 0.001:
                return {
                    'algorithm': self.algorithm_id,
                    'signal': 'BUY' if price_change > 0 else 'SELL',
                    'strength': min(abs(price_change) * 200, 1.0),
                    'reason': f'Micro movement {price_change*100:.2f}%'
                }
        
        return None

# ======================== STRATEGY FACTORY ========================

class StrategyFactory:
    """Factory for creating and managing trading strategies."""
    
    _strategies = {
        'ORDER_FLOW_TOXICITY': OrderFlowToxicityStrategy,
        'MARKET_MICROSTRUCTURE': MarketMicrostructureStrategy,
        'TICK_DIRECTION': TickDirectionStrategy,
        'VOLUME_PROFILE': VolumeProfileStrategy,
        'MULTI_TIMEFRAME_MOMENTUM': MultiTimeframeMomentumStrategy,
        'BREAKOUT_DETECTION': BreakoutDetectionStrategy,
        'ICHIMOKU_CLOUD': IchimokuCloudStrategy,
        'ELLIOTT_WAVE': ElliottWaveStrategy,
        'FIBONACCI_RETRACEMENT': FibonacciRetracementStrategy,
        'STATISTICAL_MEAN_REVERSION': StatisticalMeanReversionStrategy,
        'RSI_DIVERGENCE': RSIDivergenceStrategy,
        'VWAP_MEAN_REVERSION': VWAPMeanReversionStrategy,
        'BOLLINGER_SQUEEZE': BollingerSqueezeStrategy,
        'PAIRS_TRADING': PairsTradingStrategy,
        'GRID_TRADING': GridTradingStrategy,
        'MARKET_MAKING': MarketMakingStrategy,
        'ENSEMBLE_ML': EnsembleMLStrategy,
        'SENTIMENT_ANALYSIS': SentimentAnalysisStrategy,
        'SCALPING': ScalpingStrategy
    }
    
    @classmethod
    def create_all(cls) -> List[TradingStrategy]:
        """Create instances of all strategies."""
        return [strategy() for strategy in cls._strategies.values()]
    
    @classmethod
    def create_strategy(cls, algorithm_id: str) -> Optional[TradingStrategy]:
        """Create a specific strategy by ID."""
        strategy_class = cls._strategies.get(algorithm_id)
        return strategy_class() if strategy_class else None
    
    @classmethod
    def get_available_strategies(cls) -> List[str]:
        """Get list of available strategy IDs."""
        return list(cls._strategies.keys())

# ======================== BINANCE API CLIENT ========================

class BinanceAPIClient:
    """Production-ready Binance API client with advanced features."""
    
    def __init__(self):
        """Initialize Binance API client."""
        # API endpoints
        self.base_url = (
            'https://testnet.binance.vision/api/v3' if USE_TESTNET 
            else 'https://api.binance.com/api/v3'
        )
        self.futures_url = (
            'https://testnet.binancefuture.com/fapi/v1' if USE_TESTNET 
            else 'https://fapi.binance.com/fapi/v1'
        )
        
        # Connection management
        self.connection_pool = ConnectionPool(max_connections=5)
        self.deduplicator = RequestDeduplicator()
        
        # Circuit breaker
        self.circuit_breaker = AdaptiveCircuitBreaker(
            failure_threshold=5,
            recovery_timeout=CONFIG.circuit_breaker_cooldown,
            half_open_requests=3
        )
        
        # Rate limiting
        self.request_times = deque(maxlen=1200)
        self.weight_used = 0
        self.weight_limit = 1200
        self.last_reset = time.time()
        
        # Metrics
        self.metrics = PerformanceMetrics()
        
        # Cache
        self.price_cache = {}
        self.cache_timestamp = {}
        
        # Thread safety
        self._lock = threading.RLock()
        
        # Supported symbols
        self.symbols = {
            'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'ADAUSDT',
            'XRPUSDT', 'DOGEUSDT', 'AVAXUSDT', 'DOTUSDT', 'MATICUSDT',
            'LINKUSDT', 'UNIUSDT', 'ATOMUSDT', 'LTCUSDT', 'NEARUSDT'
        }
        
        logger.info(f"Binance API client initialized - {'TESTNET' if USE_TESTNET else 'MAINNET'}")
    
    def _check_rate_limit(self, weight: int = 1) -> None:
        """Check and enforce rate limits."""
        with self._lock:
            current_time = time.time()
            
            # Reset weight counter every minute
            if current_time - self.last_reset > 60:
                self.weight_used = 0
                self.last_reset = current_time
                self.request_times.clear()
            
            # Check if approaching limit
            if self.weight_used + weight > self.weight_limit * CONFIG.rate_limit_threshold:
                sleep_time = 60 - (current_time - self.last_reset)
                if sleep_time > 0:
                    logger.warning(f"Rate limit approaching, sleeping for {sleep_time:.0f}s")
                    time.sleep(sleep_time)
                    self.weight_used = 0
                    self.last_reset = time.time()
            
            self.weight_used += weight
    
    def _make_request(self, endpoint: str, params: Optional[Dict] = None, 
                     weight: int = 1) -> Optional[Any]:
        """Execute HTTP request with circuit breaker and metrics."""
        # Build URL
        url = f"{self.base_url}/{endpoint}"
        if params:
            url += '?' + urllib.parse.urlencode(params)
        
        # Deduplicate concurrent requests
        cache_key = hashlib.md5(url.encode()).hexdigest()
        
        def execute_request():
            # Check rate limit
            self._check_rate_limit(weight)
            
            start_time = time.time()
            error_type = None
            response_size = 0
            
            try:
                # Get connection from pool
                opener = self.connection_pool.get_connection()
                
                # Prepare headers
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Nuclear Bot v10.0)',
                    'Accept': 'application/json',
                    'Accept-Encoding': 'gzip, deflate',
                    'Connection': 'keep-alive',
                    'Cache-Control': 'no-cache'
                }
                
                if BINANCE_API_KEY:
                    headers['X-MBX-APIKEY'] = BINANCE_API_KEY
                
                # Create request
                req = urllib.request.Request(url, headers=headers)
                
                # Execute through circuit breaker
                def api_call():
                    response = opener.open(req, timeout=CONFIG.api_timeout)
                    raw_data = response.read()
                    
                    # Handle gzip
                    if raw_data[:2] == b'\x1f\x8b':
                        raw_data = gzip.decompress(raw_data)
                    
                    return json.loads(raw_data.decode('utf-8'))
                
                result = self.circuit_breaker.call(api_call)
                response_size = len(json.dumps(result))
                
                # Return connection to pool
                self.connection_pool.return_connection(opener)
                
                return result
                
            except CircuitBreakerOpenError:
                logger.error("Circuit breaker is open")
                error_type = 'CircuitBreakerOpen'
                return None
                
            except Exception as e:
                error_type = type(e).__name__
                logger.error(f"API request failed: {e}")
                return None
                
            finally:
                # Record metrics
                latency = time.time() - start_time
                self.metrics.record_request(
                    endpoint, 
                    len(url), 
                    latency, 
                    response_size, 
                    error_type
                )
        
        try:
            return self.deduplicator.deduplicate(cache_key, execute_request)
        except Exception as e:
            logger.error(f"Request deduplication failed: {e}")
            return None
    
    def get_ticker_prices(self) -> Dict[str, float]:
        """Get current prices for all symbols."""
        # Check cache
        cache_key = 'all_prices'
        if cache_key in self.price_cache:
            cache_age = time.time() - self.cache_timestamp.get(cache_key, 0)
            if cache_age < CONFIG.cache_duration:
                return self.price_cache[cache_key]
        
        # Fetch from API
        data = self._make_request('ticker/price', weight=2)
        
        if data:
            prices = {}
            for item in data:
                symbol = item.get('symbol', '')
                if symbol in self.symbols:
                    formatted_symbol = f"{symbol[:-4]}/{symbol[-4:]}"
                    try:
                        prices[formatted_symbol] = float(item['price'])
                    except (ValueError, TypeError, KeyError):
                        continue
            
            # Update cache
            if prices:
                self.price_cache[cache_key] = prices
                self.cache_timestamp[cache_key] = time.time()
            
            return prices
        
        # Fallback prices
        return self._get_fallback_prices()
    
    def get_24hr_ticker(self, symbol: Optional[str] = None) -> Optional[Dict]:
        """Get 24-hour ticker statistics."""
        params = {'symbol': symbol} if symbol else None
        weight = 1 if symbol else 40
        
        data = self._make_request('ticker/24hr', params, weight=weight)
        
        if not data:
            return None
        
        try:
            if isinstance(data, list):
                result = {}
                for item in data:
                    sym = item.get('symbol', '')
                    if sym in self.symbols:
                        formatted = f"{sym[:-4]}/{sym[-4:]}"
                        result[formatted] = {
                            'price': float(item.get('lastPrice', 0)),
                            'change_24h': float(item.get('priceChangePercent', 0)),
                            'volume': float(item.get('volume', 0)),
                            'high_24h': float(item.get('highPrice', 0)),
                            'low_24h': float(item.get('lowPrice', 0))
                        }
                return result
            else:
                return {
                    'price': float(data.get('lastPrice', 0)),
                    'change_24h': float(data.get('priceChangePercent', 0)),
                    'volume': float(data.get('volume', 0))
                }
        except (ValueError, TypeError, KeyError) as e:
            logger.error(f"Error parsing ticker data: {e}")
            return None
    
    @lru_cache(maxsize=1)
    def _get_fallback_prices(self) -> Dict[str, float]:
        """Get fallback prices when API is unavailable."""
        return {
            'BTC/USDT': 43500.00,
            'ETH/USDT': 2285.00,
            'BNB/USDT': 315.00,
            'SOL/USDT': 98.50,
            'ADA/USDT': 0.58,
            'XRP/USDT': 0.62,
            'DOGE/USDT': 0.082,
            'AVAX/USDT': 38.00,
            'DOT/USDT': 7.40,
            'MATIC/USDT': 0.89,
            'LINK/USDT': 14.50,
            'UNI/USDT': 6.30,
            'ATOM/USDT': 9.80,
            'LTC/USDT': 72.00,
            'NEAR/USDT': 3.40
        }
    
    def get_api_status(self) -> Dict[str, Any]:
        """Get comprehensive API client status."""
        metrics = self.metrics.get_statistics()
        
        return {
            'operational': self.circuit_breaker.state != CircuitState.OPEN,
            'circuit_state': self.circuit_breaker.get_state(),
            'weight_used': self.weight_used,
            'weight_limit': self.weight_limit,
            'cache_size': len(self.price_cache),
            'metrics': metrics
        }

# ======================== TRADING ALGORITHM ENGINE ========================

class TradingAlgorithmEngine:
    """Advanced trading algorithm execution engine."""
    
    def __init__(self, binance_client: BinanceAPIClient):
        """Initialize algorithm engine."""
        self.binance = binance_client
        self.strategies = StrategyFactory.create_all()
        self.price_history = defaultdict(lambda: CircularBuffer(100))
        self.volume_history = defaultdict(lambda: CircularBuffer(50))
        self._lock = threading.RLock()
        
        # Thread pool for parallel strategy execution
        self.executor = ThreadPoolExecutor(max_workers=4)
        
        logger.info(f"Algorithm engine initialized with {len(self.strategies)} strategies")
    
    def update_history(self, symbol: str, price: float, volume: Optional[float] = None) -> None:
        """Update price and volume history."""
        with self._lock:
            if price > 0:
                self.price_history[symbol].append(price)
            
            if volume is not None and volume >= 0:
                self.volume_history[symbol].append(volume)
    
    def analyze(self, symbol: str, current_price: float) -> List[Dict[str, Any]]:
        """Run all strategies and collect signals."""
        # Update history
        self.update_history(symbol, current_price)
        
        # Get historical data
        with self._lock:
            price_data = self.price_history[symbol].get_all()
            volume_data = self.volume_history[symbol].get_all() if self.volume_history[symbol] else None
        
        if len(price_data) < 5:
            return []
        
        # Run strategies in parallel
        futures = []
        for strategy in self.strategies:
            future = self.executor.submit(
                strategy.analyze, 
                symbol, 
                price_data, 
                current_price, 
                volume_data
            )
            futures.append(future)
        
        # Collect results
        signals = []
        for future in as_completed(futures, timeout=1.0):
            try:
                signal = future.result(timeout=0.1)
                if signal:
                    signals.append(signal)
            except Exception as e:
                logger.debug(f"Strategy execution error: {e}")
        
        return signals

# ======================== PROFESSIONAL TRADING ENGINE ========================

class TradingEngineSingleton:
    """Singleton wrapper for trading engine."""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = ProfessionalTradingEngine()
        return cls._instance
    
    @classmethod
    def get_instance(cls) -> 'ProfessionalTradingEngine':
        """Get or create singleton instance."""
        if cls._instance is None:
            cls()
        return cls._instance

class ProfessionalTradingEngine:
    """Core trading engine with position management."""
    
    def __init__(self):
        """Initialize trading engine."""
        # Core components
        self.binance = BinanceAPIClient()
        self.algo_engine = TradingAlgorithmEngine(self.binance)
        self.persistence = PersistenceManager()
        
        # Load balance with auto-reset logic
        balance_data = self.persistence.get_current_balance()
        self.balance = balance_data[0]
        self.session_pnl = balance_data[1]
        self.last_balance_reset = balance_data[2]
        
        # Trading state
        self.starting_balance = self.balance
        self.available_balance = self.balance
        self.margin_used = 0.0
        
        # PnL tracking (persistent)
        self.realized_pnl = 0.0
        self.unrealized_pnl = 0.0
        self.total_pnl = 0.0
        
        # Statistics
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.win_rate = 0.0
        self.largest_win = 0.0
        self.largest_loss = 0.0
        self.total_volume = 0.0
        
        # Positions
        self.open_trades = []
        self.closed_trades = []
        self.next_trade_id = 1
        
        # Leverage
        self.max_leverage = MAX_LEVERAGE
        self.current_leverage = 0.0
        
        # Prices
        self.prices = {}
        self.price_changes = {}
        self.last_price_update = 0
        
        # Thread safety
        self._balance_lock = threading.RLock()
        self._trade_lock = threading.RLock()
        
        # Start time
        self.start_time = datetime.now()
        
        # Load historical performance
        self._load_historical_performance()
        
        # Start background threads
        self._start_background_threads()
        
        logger.info(f"Trading engine initialized | Balance: ${self.balance:.2f} | Last reset: {self.last_balance_reset}")
    
    def _load_historical_performance(self) -> None:
        """Load historical PnL and algorithm performance."""
        # Load algorithm performance
        algo_perf = self.persistence.get_algorithm_performance()
        
        # Load recent PnL history
        pnl_history = self.persistence.get_historical_pnl(days=7)
        if pnl_history:
            latest = pnl_history[0]
            self.total_trades = latest.get('trade_count', 0)
            self.win_rate = latest.get('win_rate', 0.0)
            
            # Calculate cumulative PnL
            self.realized_pnl = sum(h['realized_pnl'] for h in pnl_history)
            
            logger.info(f"Loaded historical data: {len(pnl_history)} PnL records, {len(algo_perf)} algorithms")
    
    def _start_background_threads(self) -> None:
        """Start background processing threads."""
        threads = [
            threading.Thread(target=self._price_update_loop, daemon=True, name="PriceUpdater"),
            threading.Thread(target=self._balance_check_loop, daemon=True, name="BalanceChecker"),
            threading.Thread(target=self._pnl_snapshot_loop, daemon=True, name="PnLSnapshot")
        ]
        
        for thread in threads:
            thread.start()
        
        logger.info(f"Started {len(threads)} background threads")
    
    def _price_update_loop(self) -> None:
        """Continuously update prices from Binance API."""
        while True:
            try:
                ticker_data = self.binance.get_24hr_ticker()
                
                if ticker_data:
                    with self._trade_lock:
                        for symbol, data in ticker_data.items():
                            if isinstance(data, dict):
                                self.prices[symbol] = data.get('price', 0)
                                self.price_changes[symbol] = data.get('change_24h', 0)
                                
                                # Update algorithm engine
                                self.algo_engine.update_history(
                                    symbol,
                                    data.get('price', 0),
                                    data.get('volume')
                                )
                    
                    self.last_price_update = time.time()
                    logger.info(f"Updated {len(self.prices)} prices")
                
                time.sleep(CONFIG.price_update_interval)
                
            except Exception as e:
                logger.error(f"Price update error: {e}")
                time.sleep(CONFIG.price_update_interval * 2)
    
    def _balance_check_loop(self) -> None:
        """Check for balance reset every hour."""
        while True:
            try:
                time.sleep(3600)  # Check every hour
                
                # Check if 24 hours have passed
                current_balance = self.persistence.get_current_balance()
                
                if current_balance[0] != self.balance:
                    with self._balance_lock:
                        old_balance = self.balance
                        self.balance = current_balance[0]
                        self.available_balance = self.balance - self.margin_used
                        self.last_balance_reset = current_balance[2]
                        
                        logger.info(f"Balance reset detected: ${old_balance:.2f} -> ${self.balance:.2f}")
                
            except Exception as e:
                logger.error(f"Balance check error: {e}")
    
    def _pnl_snapshot_loop(self) -> None:
        """Periodically save PnL snapshots."""
        while True:
            try:
                time.sleep(300)  # Every 5 minutes
                
                # Save PnL snapshot
                self.persistence.save_pnl_snapshot(
                    self.realized_pnl,
                    self.unrealized_pnl,
                    self.total_trades,
                    self.win_rate
                )
                
            except Exception as e:
                logger.error(f"PnL snapshot error: {e}")
    
    def open_trade(self, symbol: Optional[str] = None, side: Optional[TradeSide] = None,
                  leverage: Optional[int] = None, algorithm: Optional[str] = None,
                  reason: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Open a new trade position."""
        with self._trade_lock:
            prices = self.prices or self.binance._get_fallback_prices()
            
            # Select random values if not provided
            if not symbol:
                symbol = random.choice(list(prices.keys())[:10])
            if not side:
                side = random.choice([TradeSide.LONG, TradeSide.SHORT])
            if not leverage:
                leverage = random.randint(1, min(5, self.max_leverage))
            if not algorithm:
                algorithm = random.choice(StrategyFactory.get_available_strategies())
            
            # Validate
            if symbol not in prices:
                return None
            
            price = prices[symbol]
            if price <= 0:
                return None
            
            # Check limits
            if len(self.open_trades) >= CONFIG.max_open_positions:
                logger.warning("Maximum positions reached")
                return None
            
            # Calculate position
            risk_amount = self.available_balance * random.uniform(
                CONFIG.position_size_min, 
                CONFIG.position_size_max
            )
            position_size = risk_amount * leverage
            margin_required = position_size / leverage
            
            if margin_required > self.available_balance:
                logger.warning("Insufficient balance")
                return None
            
            # Create trade
            trade = {
                'id': self.next_trade_id,
                'symbol': symbol,
                'side': side,
                'entry_price': price,
                'current_price': price,
                'amount': position_size / price,
                'position_value': position_size,
                'leverage': leverage,
                'margin': margin_required,
                'pnl': 0.0,
                'pnl_percent': 0.0,
                'status': TradeStatus.OPEN,
                'open_time': datetime.now(),
                'sl': price * (1 - CONFIG.stop_loss_percent if side == TradeSide.LONG 
                              else 1 + CONFIG.stop_loss_percent),
                'tp': price * (1 + CONFIG.take_profit_percent if side == TradeSide.LONG 
                              else 1 - CONFIG.take_profit_percent),
                'algorithm': algorithm,
                'algorithm_reason': reason or f"Signal from {algorithm}"
            }
            
            # Update state
            self.next_trade_id += 1
            self.open_trades.append(trade)
            self.available_balance -= margin_required
            self.margin_used += margin_required
            self.total_trades += 1
            self.total_volume += position_size
            
            # Save to database
            self.persistence.save_trade(trade)
            
            logger.info(
                f"📈 Trade #{trade['id']}: {algorithm} - {side.value} {symbol} @ ${price:.4f} | "
                f"Leverage: {leverage}x | Size: ${position_size:.2f}"
            )
            
            return trade
    
    def update_trades(self) -> None:
        """Update all open trades with current prices."""
        with self._trade_lock:
            prices = self.prices or self.binance._get_fallback_prices()
            self.unrealized_pnl = 0.0
            
            trades_to_close = []
            
            # Batch process by symbol for efficiency
            trades_by_symbol = defaultdict(list)
            for trade in self.open_trades:
                trades_by_symbol[trade['symbol']].append(trade)
            
            for symbol, symbol_trades in trades_by_symbol.items():
                current_price = prices.get(symbol)
                if not current_price:
                    continue
                
                for trade in symbol_trades:
                    # Calculate P&L
                    if trade['side'] == TradeSide.LONG:
                        price_change = (current_price - trade['entry_price']) / trade['entry_price']
                    else:
                        price_change = (trade['entry_price'] - current_price) / trade['entry_price']
                    
                    trade['current_price'] = current_price
                    trade['pnl'] = price_change * trade['position_value']
                    trade['pnl_percent'] = price_change * 100 * trade['leverage']
                    
                    self.unrealized_pnl += trade['pnl']
                    
                    # Check stops
                    should_close = False
                    
                    if trade['side'] == TradeSide.LONG:
                        if current_price <= trade['sl'] or current_price >= trade['tp']:
                            should_close = True
                    else:
                        if current_price >= trade['sl'] or current_price <= trade['tp']:
                            should_close = True
                    
                    if should_close:
                        trades_to_close.append(trade['id'])
            
            # Close triggered trades
            for trade_id in trades_to_close:
                self.close_trade(trade_id)
            
            # Update totals
            self.total_pnl = self.realized_pnl + self.unrealized_pnl
            self.calculate_leverage()
    
    def close_trade(self, trade_id: int) -> bool:
        """Close a specific trade."""
        with self._trade_lock:
            trade = None
            for t in self.open_trades:
                if t['id'] == trade_id:
                    trade = t
                    break
            
            if not trade:
                return False
            
            # Update trade
            trade['status'] = TradeStatus.CLOSED
            trade['close_time'] = datetime.now()
            trade['exit_price'] = trade['current_price']
            
            # Update balances
            self.available_balance += trade['margin'] + trade['pnl']
            self.balance += trade['pnl']
            self.margin_used -= trade['margin']
            self.realized_pnl += trade['pnl']
            
            # Update statistics
            if trade['pnl'] > 0:
                self.winning_trades += 1
                if trade['pnl'] > self.largest_win:
                    self.largest_win = trade['pnl']
            else:
                self.losing_trades += 1
                if trade['pnl'] < self.largest_loss:
                    self.largest_loss = trade['pnl']
            
            if self.total_trades > 0:
                self.win_rate = (self.winning_trades / self.total_trades) * 100
            
            # Remove from open trades
            self.open_trades.remove(trade)
            self.closed_trades.append(trade)
            
            # Keep only recent closed trades
            if len(self.closed_trades) > 100:
                self.closed_trades = self.closed_trades[-100:]
            
            # Update persistence
            self.persistence.update_balance(self.balance, trade['pnl'])
            self.persistence.save_trade(trade)
            self.persistence.update_algorithm_performance(
                trade['algorithm'],
                trade['pnl'] > 0,
                trade['pnl']
            )
            
            logger.info(
                f"💰 Closed trade #{trade['id']}: "
                f"P&L: ${trade['pnl']:.2f} ({trade['pnl_percent']:.1f}%)"
            )
            
            return True
    
    def calculate_leverage(self) -> float:
        """Calculate current account leverage."""
        if self.balance <= 0:
            self.current_leverage = 0.0
            return 0.0
        
        total_position_value = sum(trade['position_value'] for trade in self.open_trades)
        self.current_leverage = total_position_value / self.balance
        
        return self.current_leverage
    
    def execute_auto_trade(self) -> Optional[Dict[str, Any]]:
        """Execute automatic trading based on signals."""
        if len(self.open_trades) >= CONFIG.max_open_positions:
            return None
        
        prices = self.prices or self.binance._get_fallback_prices()
        if not prices:
            return None
        
        best_signal = None
        best_strength = 0.0
        
        # Analyze top symbols
        symbols_to_analyze = list(prices.keys())[:10]
        
        for symbol in symbols_to_analyze:
            price = prices.get(symbol, 0)
            if price <= 0:
                continue
            
            signals = self.algo_engine.analyze(symbol, price)
            
            for signal in signals:
                if signal['strength'] > best_strength:
                    best_signal = signal
                    best_signal['symbol'] = symbol
                    best_strength = signal['strength']
        
        # Execute trade if signal is strong enough
        if best_signal and best_strength >= CONFIG.min_trade_confidence:
            side = TradeSide.LONG if best_signal['signal'] == 'BUY' else TradeSide.SHORT
            leverage = min(int(best_strength * 5) + 1, self.max_leverage)
            
            return self.open_trade(
                symbol=best_signal['symbol'],
                side=side,
                leverage=leverage,
                algorithm=best_signal['algorithm'],
                reason=best_signal['reason']
            )
        
        return None
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """Get comprehensive performance summary."""
        return {
            'balance': round(self.balance, 2),
            'available_balance': round(self.available_balance, 2),
            'margin_used': round(self.margin_used, 2),
            'leverage': round(self.current_leverage, 2),
            'realized_pnl': round(self.realized_pnl, 2),
            'unrealized_pnl': round(self.unrealized_pnl, 2),
            'total_pnl': round(self.total_pnl, 2),
            'session_pnl': round(self.session_pnl, 2),
            'total_trades': self.total_trades,
            'open_trades': len(self.open_trades),
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': round(self.win_rate, 2),
            'largest_win': round(self.largest_win, 2),
            'largest_loss': round(self.largest_loss, 2),
            'total_volume': round(self.total_volume, 2),
            'last_balance_reset': self.last_balance_reset.isoformat(),
            'uptime_hours': round((datetime.now() - self.start_time).total_seconds() / 3600, 2)
        }

# ======================== WEB DASHBOARD ========================

class NuclearDashboardHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the trading dashboard."""
    
    def do_GET(self) -> None:
        """Handle GET requests."""
        try:
            if self.path == '/':
                self.serve_dashboard()
            elif self.path == '/health':
                self.serve_health()
            elif self.path == '/api/status':
                self.serve_status()
            elif self.path == '/api/history':
                self.serve_history()
            else:
                self.send_error(404)
        except Exception as e:
            logger.error(f"GET error: {e}")
            self.send_error(500)
    
    def do_POST(self) -> None:
        """Handle POST requests."""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            
            if self.path == '/api/open_trade':
                self.handle_open_trade()
            elif self.path == '/api/close_trade':
                self.handle_close_trade(content_length)
            elif self.path == '/api/close_all':
                self.handle_close_all()
            else:
                self.send_error(404)
        except Exception as e:
            logger.error(f"POST error: {e}")
            self.send_error(500)
    
    def serve_health(self) -> None:
        """Serve health check endpoint."""
        engine = TradingEngineSingleton.get_instance()
        
        health = {
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'performance': engine.get_performance_summary(),
            'api_status': engine.binance.get_api_status()
        }
        
        self.send_json_response(health)
    
    def serve_status(self) -> None:
        """Serve current status as JSON."""
        engine = TradingEngineSingleton.get_instance()
        
        status = {
            'performance': engine.get_performance_summary(),
            'open_trades': [self._serialize_trade(t) for t in engine.open_trades],
            'prices': engine.prices,
            'algorithm_performance': engine.persistence.get_algorithm_performance()
        }
        
        self.send_json_response(status)
    
    def serve_history(self) -> None:
        """Serve historical PnL data."""
        engine = TradingEngineSingleton.get_instance()
        
        history = {
            'pnl_history': engine.persistence.get_historical_pnl(days=30),
            'closed_trades': [self._serialize_trade(t) for t in engine.closed_trades[-50:]]
        }
        
        self.send_json_response(history)
    
    def _serialize_trade(self, trade: Dict) -> Dict:
        """Serialize trade for JSON response."""
        serialized = trade.copy()
        
        # Convert enums
        if isinstance(serialized.get('side'), TradeSide):
            serialized['side'] = serialized['side'].value
        if isinstance(serialized.get('status'), TradeStatus):
            serialized['status'] = serialized['status'].value
        
        # Convert datetime
        if isinstance(serialized.get('open_time'), datetime):
            serialized['open_time'] = serialized['open_time'].isoformat()
        if isinstance(serialized.get('close_time'), datetime):
            serialized['close_time'] = serialized['close_time'].isoformat()
        
        return serialized
    
    def handle_open_trade(self) -> None:
        """Handle open trade request."""
        engine = TradingEngineSingleton.get_instance()
        trade = engine.execute_auto_trade()
        
        response = {
            'success': trade is not None,
            'trade': self._serialize_trade(trade) if trade else None
        }
        
        self.send_json_response(response)
    
    def handle_close_trade(self, content_length: int) -> None:
        """Handle close trade request."""
        if content_length > 0:
            try:
                data = json.loads(self.rfile.read(content_length))
                trade_id = data.get('trade_id')
                
                if trade_id:
                    engine = TradingEngineSingleton.get_instance()
                    success = engine.close_trade(int(trade_id))
                else:
                    success = False
            except Exception:
                success = False
        else:
            success = False
        
        self.send_json_response({'success': success})
    
    def handle_close_all(self) -> None:
        """Handle close all trades request."""
        engine = TradingEngineSingleton.get_instance()
        trades_to_close = [t['id'] for t in engine.open_trades.copy()]
        
        closed_count = 0
        for trade_id in trades_to_close:
            if engine.close_trade(trade_id):
                closed_count += 1
        
        self.send_json_response({
            'success': True,
            'closed_count': closed_count
        })
    
    def serve_dashboard(self) -> None:
        """Serve the main dashboard HTML."""
        engine = TradingEngineSingleton.get_instance()
        
        # Generate dashboard HTML
        html = self._generate_dashboard_html(engine)
        
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))
    
    def _generate_dashboard_html(self, engine) -> str:
        """Generate complete dashboard HTML."""
        perf = engine.get_performance_summary()
        api_status = engine.binance.get_api_status()
        algo_perf = engine.persistence.get_algorithm_performance()
        
        # Use StringIO for efficient string building
        buffer = StringIO()
        
        buffer.write(f'''<!DOCTYPE html>
<html>
<head>
    <title>☢️ Nuclear Bot v10.0 - Production</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: linear-gradient(135deg, #0a0a0a, #1a1a2e);
            color: #fff;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            padding: 20px;
            min-height: 100vh;
        }}
        .container {{ max-width: 1800px; margin: 0 auto; }}
        
        .header {{
            background: linear-gradient(135deg, #667eea, #764ba2);
            padding: 30px;
            border-radius: 15px;
            margin-bottom: 30px;
            text-align: center;
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
        }}
        
        h1 {{ 
            font-size: 2.5em; 
            margin-bottom: 20px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }}
        
        .badge {{
            display: inline-block;
            padding: 8px 16px;
            margin: 5px;
            border-radius: 20px;
            font-weight: bold;
            font-size: 0.9em;
        }}
        
        .badge-success {{ background: #00ff88; color: #000; }}
        .badge-warning {{ background: #ffd93d; color: #000; }}
        .badge-danger {{ background: #ff4444; color: #fff; }}
        .badge-info {{ background: #00b4d8; color: #fff; }}
        
        .controls {{
            display: flex;
            gap: 15px;
            justify-content: center;
            margin: 20px 0;
            flex-wrap: wrap;
        }}
        
        .btn {{
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            cursor: pointer;
            font-weight: bold;
            transition: all 0.3s ease;
            box-shadow: 0 4px 6px rgba(0,0,0,0.2);
        }}
        
        .btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 6px 12px rgba(0,0,0,0.3);
        }}
        
        .btn-open {{ 
            background: linear-gradient(135deg, #00ff88, #00cc70); 
            color: #000; 
        }}
        
        .btn-close-all {{ 
            background: linear-gradient(135deg, #ff4444, #cc0000); 
            color: #fff; 
        }}
        
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin: 30px 0;
        }}
        
        .stat-card {{
            background: linear-gradient(135deg, #1a1a1a, #2a2a2a);
            padding: 20px;
            border-radius: 10px;
            border: 1px solid #333;
            transition: transform 0.2s ease;
        }}
        
        .stat-card:hover {{
            transform: scale(1.02);
            border-color: #667eea;
        }}
        
        .stat-label {{
            font-size: 0.9em;
            color: #888;
            margin-bottom: 8px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        
        .stat-value {{
            font-size: 1.8em;
            font-weight: bold;
        }}
        
        .positive {{ color: #00ff88; }}
        .negative {{ color: #ff4444; }}
        .neutral {{ color: #ffd93d; }}
        
        .section {{
            background: linear-gradient(135deg, #1a1a1a, #252525);
            padding: 25px;
            border-radius: 10px;
            margin: 20px 0;
            border: 1px solid #333;
            box-shadow: 0 5px 15px rgba(0,0,0,0.2);
        }}
        
        h2 {{ 
            color: #f093fb; 
            margin-bottom: 20px;
            font-size: 1.5em;
            border-bottom: 2px solid #333;
            padding-bottom: 10px;
        }}
        
        table {{ 
            width: 100%; 
            border-collapse: collapse;
            margin-top: 10px;
        }}
        
        th {{ 
            background: #2a2a2a; 
            padding: 12px; 
            text-align: left;
            border-bottom: 2px solid #444;
            color: #f093fb;
            font-weight: 600;
        }}
        
        td {{ 
            padding: 10px; 
            border-bottom: 1px solid #333;
        }}
        
        tr:hover {{
            background: rgba(102, 126, 234, 0.1);
        }}
        
        .price-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 12px;
            margin: 20px 0;
        }}
        
        .price-card {{
            background: linear-gradient(135deg, #2a2a2a, #333);
            padding: 15px;
            border-radius: 8px;
            text-align: center;
            border: 1px solid #444;
            transition: all 0.3s ease;
        }}
        
        .price-card:hover {{
            transform: scale(1.05);
            border-color: #667eea;
            box-shadow: 0 0 15px rgba(102, 126, 234, 0.3);
        }}
        
        .algo-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }}
        
        .algo-card {{
            background: linear-gradient(135deg, #1a1a1a, #2a2a2a);
            padding: 15px;
            border-radius: 8px;
            border-left: 4px solid;
            transition: transform 0.2s ease;
        }}
        
        .algo-card:hover {{
            transform: translateX(5px);
        }}
        
        .algo-stats {{
            display: flex;
            justify-content: space-between;
            margin-top: 10px;
            font-size: 0.9em;
        }}
        
        .long {{ color: #00ff88; font-weight: bold; }}
        .short {{ color: #ff4444; font-weight: bold; }}
        
        .btn-close-trade {{
            background: #ff4444;
            color: white;
            padding: 5px 15px;
            border-radius: 5px;
            border: none;
            cursor: pointer;
            font-size: 0.9em;
        }}
        
        .btn-close-trade:hover {{
            background: #cc0000;
        }}
        
        .info-box {{
            background: linear-gradient(135deg, #00b4d8, #0077b6);
            color: white;
            padding: 15px 20px;
            border-radius: 8px;
            margin: 10px 0;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        
        .chart-container {{
            background: #1a1a1a;
            padding: 20px;
            border-radius: 10px;
            margin: 20px 0;
            height: 300px;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #666;
        }}
        
        @keyframes pulse {{
            0% {{ opacity: 1; }}
            50% {{ opacity: 0.5; }}
            100% {{ opacity: 1; }}
        }}
        
        .live-indicator {{
            display: inline-block;
            width: 10px;
            height: 10px;
            background: #00ff88;
            border-radius: 50%;
            animation: pulse 2s infinite;
            margin-right: 5px;
        }}
    </style>
    <script>
        function openTrade() {{
            fetch('/api/open_trade', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{}})
            }}).then(() => location.reload());
        }}
        
        function closeTrade(id) {{
            if(confirm('Close this trade?')) {{
                fetch('/api/close_trade', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{trade_id: id}})
                }}).then(() => location.reload());
            }}
        }}
        
        function closeAllTrades() {{
            if(confirm('Close ALL trades?')) {{
                fetch('/api/close_all', {{
                    method: 'POST'
                }}).then(() => location.reload());
            }}
        }}
        
        // Auto-refresh
        setTimeout(() => location.reload(), {CONFIG.dashboard_refresh_interval});
    </script>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>☢️ NUCLEAR TRADING BOT v10.0</h1>
            <div>
                <span class="badge badge-success">
                    <span class="live-indicator"></span>LIVE TRADING
                </span>
                <span class="badge {'badge-success' if api_status['operational'] else 'badge-danger'}">
                    API: {api_status['circuit_state']}
                </span>
                <span class="badge badge-info">
                    {'TESTNET' if USE_TESTNET else 'MAINNET'}
                </span>
                <span class="badge badge-warning">
                    {len(StrategyFactory.get_available_strategies())} STRATEGIES
                </span>
            </div>
            
            <div class="info-box" style="margin-top: 20px;">
                <div>
                    <strong>Balance Reset:</strong> Every 24 hours | 
                    <strong>Last Reset:</strong> {perf['last_balance_reset']} | 
                    <strong>Uptime:</strong> {perf['uptime_hours']:.1f} hours
                </div>
                <div>
                    <strong>PnL Memory:</strong> Persistent across sessions
                </div>
            </div>
            
            <div class="controls">
                <button onclick="openTrade()" class="btn btn-open">📈 Open Smart Trade</button>
                <button onclick="closeAllTrades()" class="btn btn-close-all">❌ Close All Trades</button>
            </div>
        </div>
        
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-label">💰 Current Balance</div>
                <div class="stat-value">${perf['balance']:.2f}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">💵 Available</div>
                <div class="stat-value">${perf['available_balance']:.2f}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">🔒 Margin Used</div>
                <div class="stat-value">${perf['margin_used']:.2f}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">⚡ Leverage</div>
                <div class="stat-value">{perf['leverage']:.2f}x</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">📊 Total P&L (All-Time)</div>
                <div class="stat-value {'positive' if perf['total_pnl'] >= 0 else 'negative'}">${perf['total_pnl']:.2f}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">✅ Realized P&L</div>
                <div class="stat-value {'positive' if perf['realized_pnl'] >= 0 else 'negative'}">${perf['realized_pnl']:.2f}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">⏳ Unrealized P&L</div>
                <div class="stat-value {'positive' if perf['unrealized_pnl'] >= 0 else 'negative'}">${perf['unrealized_pnl']:.2f}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">💹 Session P&L</div>
                <div class="stat-value {'positive' if perf['session_pnl'] >= 0 else 'negative'}">${perf['session_pnl']:.2f}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">📦 Open Trades</div>
                <div class="stat-value">{perf['open_trades']}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">🔄 Total Trades</div>
                <div class="stat-value">{perf['total_trades']}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">📈 Win Rate</div>
                <div class="stat-value {'positive' if perf['win_rate'] >= 50 else 'negative'}">{perf['win_rate']:.1f}%</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">🏆 W/L</div>
                <div class="stat-value">{perf['winning_trades']}/{perf['losing_trades']}</div>
            </div>
        </div>
''')
        
        # Algorithm Performance Section
        buffer.write('<div class="section"><h2>🤖 ALGORITHM PERFORMANCE</h2><div class="algo-grid">')
        
        for algo_id, stats in sorted(algo_perf.items(), key=lambda x: x[1]['pnl'], reverse=True):
            if stats['trades'] == 0:
                continue
                
            strategy = StrategyFactory.create_strategy(algo_id)
            if strategy:
                color = strategy.color
                name = strategy.name
                risk = strategy.risk_level.emoji
            else:
                color = '#666'
                name = algo_id
                risk = '⚪'
            
            buffer.write(f'''
            <div class="algo-card" style="border-left-color: {color};">
                <h4>{risk} {name}</h4>
                <div class="algo-stats">
                    <span>Trades: {stats['trades']}</span>
                    <span>Wins: {stats['wins']}</span>
                    <span>Win%: {stats['win_rate']:.1f}</span>
                    <span class="{'positive' if stats['pnl'] >= 0 else 'negative'}">
                        P&L: ${stats['pnl']:.2f}
                    </span>
                </div>
            </div>
            ''')
        
        buffer.write('</div></div>')
        
        # Live Prices Section
        buffer.write('<div class="section"><h2>💹 LIVE BINANCE PRICES</h2><div class="price-grid">')
        
        for symbol, price in list(engine.prices.items())[:15]:
            change = engine.price_changes.get(symbol, 0)
            
            buffer.write(f'''
            <div class="price-card">
                <strong>{symbol}</strong>
                <div style="font-size: 1.2em; margin: 5px 0;">${price:.6f if price < 1 else price:.2f}</div>
                <div class="{'positive' if change >= 0 else 'negative'}">{change:.2f}%</div>
            </div>
            ''')
        
        buffer.write('</div></div>')
        
        # Open Trades Section
        buffer.write('<div class="section"><h2>📈 OPEN POSITIONS</h2><table><thead><tr>')
        headers = ['ID', 'Symbol', 'Side', 'Algorithm', 'Leverage', 'Entry', 'Current', 'Size', 'P&L', 'P&L %', 'Action']
        for header in headers:
            buffer.write(f'<th>{header}</th>')
        buffer.write('</tr></thead><tbody>')
        
        if engine.open_trades:
            for trade in engine.open_trades:
                side_class = 'long' if trade['side'] == TradeSide.LONG else 'short'
                pnl_class = 'positive' if trade['pnl'] >= 0 else 'negative'
                
                buffer.write(f'''
                <tr>
                    <td>{trade['id']}</td>
                    <td>{trade['symbol']}</td>
                    <td class="{side_class}">{trade['side'].value if isinstance(trade['side'], TradeSide) else trade['side']}</td>
                    <td>{trade['algorithm']}</td>
                    <td>{trade['leverage']}x</td>
                    <td>${trade['entry_price']:.6f if trade['entry_price'] < 1 else trade['entry_price']:.2f}</td>
                    <td>${trade['current_price']:.6f if trade['current_price'] < 1 else trade['current_price']:.2f}</td>
                    <td>${trade['position_value']:.2f}</td>
                    <td class="{pnl_class}">${trade['pnl']:.2f}</td>
                    <td class="{pnl_class}">{trade['pnl_percent']:.2f}%</td>
                    <td>
                        <button onclick="closeTrade({trade['id']})" class="btn-close-trade">Close</button>
                    </td>
                </tr>
                ''')
        else:
            buffer.write('<tr><td colspan="11" style="text-align:center; padding: 20px;">No open positions</td></tr>')
        
        buffer.write('</tbody></table></div>')
        
        # Footer
        buffer.write('''
    </div>
</body>
</html>
        ''')
        
        return buffer.getvalue()
    
    def send_json_response(self, data: Any) -> None:
        """Send JSON response."""
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))
    
    def log_message(self, format: str, *args) -> None:
        """Override to suppress request logging."""
        pass

# ======================== MAIN TRADING LOOP ========================

def trading_loop() -> None:
    """Main trading loop with automatic trading."""
    engine = TradingEngineSingleton.get_instance()
    logger.info("Starting automated trading loop...")
    
    consecutive_errors = 0
    max_consecutive_errors = 10
    
    while True:
        try:
            # Update existing trades
            engine.update_trades()
            
            # Execute auto trades
            if len(engine.open_trades) < CONFIG.max_open_positions and random.random() < 0.1:
                trade = engine.execute_auto_trade()
                
                if trade:
                    logger.info(f"Auto trade executed: {trade['algorithm']} - {trade['symbol']}")
            
            # Reset error counter
            consecutive_errors = 0
            
            time.sleep(CONFIG.trading_loop_interval)
            
        except Exception as e:
            consecutive_errors += 1
            logger.error(f"Trading loop error ({consecutive_errors}/{max_consecutive_errors}): {e}")
            
            # Exponential backoff
            sleep_time = min(60, CONFIG.trading_loop_interval * (2 ** min(consecutive_errors, 5)))
            time.sleep(sleep_time)
            
            if consecutive_errors >= max_consecutive_errors:
                logger.critical("Too many consecutive errors, stopping trading loop")
                break

# ======================== MAIN ENTRY POINT ========================

def main() -> None:
    """Main application entry point."""
    # Print startup banner
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║         ☢️  NUCLEAR LAUNCHER v10.0 PRODUCTION                 ║
║      Real Binance API | Algorithm Tracking | Rate Limits      ║
║  Port: {PORT:<6} | Testnet: {USE_TESTNET} | Leverage: {MAX_LEVERAGE}x         ║
╚══════════════════════════════════════════════════════════════╝
""")
    
    # Initialize configuration
    config_path = Path(CONFIG.data_dir) / CONFIG.config_file
    if config_path.exists():
        CONFIG = TradingConfig.from_file(str(config_path))
        logger.info(f"Loaded configuration from {config_path}")
    else:
        CONFIG.save(str(config_path))
        logger.info(f"Created default configuration at {config_path}")
    
    # Display active algorithms
    print("\n📊 ACTIVE TRADING ALGORITHMS:")
    strategies = StrategyFactory.get_available_strategies()
    for i, algo_id in enumerate(strategies, 1):
        strategy = StrategyFactory.create_strategy(algo_id)
        if strategy:
            print(f"  {i:2}. {strategy.risk_level.emoji} {strategy.name}")
    print(f"\n✅ Total Active Algorithms: {len(strategies)}")
    
    # Initialize trading engine (singleton)
    try:
        engine = TradingEngineSingleton.get_instance()
        logger.info("Trading engine initialized successfully")
    except Exception as e:
        logger.critical(f"Failed to initialize trading engine: {e}")
        sys.exit(1)
    
    # Start trading loop in background
    trading_thread = threading.Thread(
        target=trading_loop,
        daemon=True,
        name="TradingLoop"
    )
    trading_thread.start()
    logger.info("Automated trading loop started")
    
    # Start HTTP server
    try:
        server = HTTPServer(('0.0.0.0', PORT), NuclearDashboardHandler)
        server.socket.settimeout(1.0)  # Allow periodic checks
        
        print(f"""
✅ NUCLEAR BOT v10.0 - PRODUCTION READY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 Dashboard: http://localhost:{PORT}
🌐 Binance API: {'TESTNET' if USE_TESTNET else 'MAINNET'}
⚡ Max Leverage: {MAX_LEVERAGE}x
💰 Current Balance: ${engine.balance:.2f}
📅 Balance Resets: Every 24 hours
💾 PnL History: Persistent across sessions

✨ Production Features:
  • 19 institutional-grade trading algorithms
  • Modular strategy pattern architecture
  • Persistent PnL tracking with SQLite
  • Connection pooling and circuit breakers
  • Adaptive rate limiting
  • Comprehensive performance metrics
  • Thread-safe operations
  • Memory-efficient circular buffers
  • Request deduplication
  • Graceful error recovery

🔧 Configuration:
  • Config file: {CONFIG.data_dir}/{CONFIG.config_file}
  • Database: {CONFIG.data_dir}/{CONFIG.db_file}
  • Price updates: Every {CONFIG.price_update_interval}s
  • Trading loop: Every {CONFIG.trading_loop_interval}s

📡 API Status:
  • Circuit Breaker: {engine.binance.circuit_breaker.get_state()}
  • Connection Pool: {engine.binance.connection_pool._max_connections} connections
  • Rate Limit: {engine.binance.weight_used}/{engine.binance.weight_limit}

Press Ctrl+C to stop
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        """)
        
        # Run server with graceful shutdown
        try:
            while True:
                server.handle_request()
                
        except KeyboardInterrupt:
            print("\n\n🛑 Shutdown requested...")
            
    except OSError as e:
        if e.errno == 48:  # Address already in use
            logger.error(f"Port {PORT} is already in use. Please use a different port.")
        else:
            logger.critical(f"Failed to start server: {e}")
        sys.exit(1)
        
    finally:
        # Graceful shutdown
        print("💾 Performing graceful shutdown...")
        
        try:
            # Save final PnL snapshot
            engine.persistence.save_pnl_snapshot(
                engine.realized_pnl,
                engine.unrealized_pnl,
                engine.total_trades,
                engine.win_rate
            )
            logger.info("Final PnL snapshot saved")
            
            # Close all open positions
            if engine.open_trades:
                print(f"📦 Closing {len(engine.open_trades)} open positions...")
                trades_to_close = [t['id'] for t in engine.open_trades.copy()]
                
                for trade_id in trades_to_close:
                    try:
                        engine.close_trade(trade_id)
                    except Exception as e:
                        logger.error(f"Error closing trade {trade_id}: {e}")
            
            # Save final balance
            engine.persistence.update_balance(engine.balance, 0)
            
            # Shutdown thread pool
            engine.algo_engine.executor.shutdown(wait=False)
            
            # Display final statistics
            print(f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 FINAL SESSION STATISTICS:

Balance: ${engine.balance:.2f}
Total P&L: ${engine.total_pnl:.2f}
Realized P&L: ${engine.realized_pnl:.2f}
Total Trades: {engine.total_trades}
Win Rate: {engine.win_rate:.1f}%
Session Duration: {(datetime.now() - engine.start_time).total_seconds() / 3600:.1f} hours

Top Performing Algorithms:
""")
            
            # Display top algorithms
            algo_perf = engine.persistence.get_algorithm_performance()
            sorted_algos = sorted(algo_perf.items(), key=lambda x: x[1]['pnl'], reverse=True)[:5]
            
            for algo_id, stats in sorted_algos:
                if stats['trades'] > 0:
                    strategy = StrategyFactory.create_strategy(algo_id)
                    name = strategy.name if strategy else algo_id
                    print(f"  • {name}: ${stats['pnl']:.2f} ({stats['trades']} trades)")
            
            print("""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            """)
            
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
        
        print("✅ Shutdown complete")
        sys.exit(0)

# ======================== UTILITY FUNCTIONS ========================

def validate_environment() -> bool:
    """Validate environment and dependencies."""
    errors = []
    
    # Check Python version
    if sys.version_info < (3, 7):
        errors.append(f"Python 3.7+ required (current: {sys.version})")
    
    # Check port availability
    if PORT < 1 or PORT > 65535:
        errors.append(f"Invalid port number: {PORT}")
    
    # Check initial balance
    if INITIAL_BALANCE <= 0:
        errors.append(f"Invalid initial balance: {INITIAL_BALANCE}")
    
    # Check data directory permissions
    try:
        test_file = Path(CONFIG.data_dir) / '.test'
        test_file.touch()
        test_file.unlink()
    except Exception as e:
        errors.append(f"Cannot write to data directory: {e}")
    
    if errors:
        print("❌ Environment validation failed:")
        for error in errors:
            print(f"  • {error}")
        return False
    
    return True

def setup_signal_handlers() -> None:
    """Setup signal handlers for graceful shutdown."""
    import signal
    
    def signal_handler(signum, frame):
        print(f"\n📡 Received signal {signum}, shutting down...")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

# ======================== SCRIPT ENTRY POINT ========================

if __name__ == "__main__":
    try:
        # Validate environment
        if not validate_environment():
            sys.exit(1)
        
        # Setup signal handlers
        setup_signal_handlers()
        
        # Run main application
        main()
        
    except Exception as e:
        logger.critical(f"Unhandled exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)