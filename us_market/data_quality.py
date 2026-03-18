#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Data Quality Utility Module
- Provides metadata wrapping for all output files
- Validates data for common issues (NaN, zeros, etc.)
- Standardizes timestamps and source tracking
"""

import os
import json
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Any
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class DataQualityWrapper:
    """Wrapper class to add metadata and validation to all data outputs"""
    
    @staticmethod
    def wrap_output(
        data: Any,
        source: str,
        row_count: int = None,
        data_quality: str = 'actual',
        notes: str = None
    ) -> Dict:
        """
        Wrap data with standard metadata.
        
        Args:
            data: The actual data (dict, list, etc.)
            source: Data source identifier (e.g., 'yfinance', 'wikipedia', 'gemini')
            row_count: Number of data rows (if applicable)
            data_quality: 'actual' | 'stale' | 'simulated' | 'partial'
            notes: Optional notes about data quality issues
        
        Returns:
            Dict with 'metadata' and 'data' keys
        """
        metadata = {
            'as_of_date': datetime.now().strftime('%Y-%m-%d'),
            'fetch_time': datetime.now().isoformat(),
            'source': source,
            'data_quality': data_quality,
        }
        
        if row_count is not None:
            metadata['row_count'] = row_count
        
        if notes:
            metadata['notes'] = notes
        
        return {
            'metadata': metadata,
            'data': data
        }
    
    @staticmethod
    def validate_dataframe(df: pd.DataFrame, price_col: str = 'current_price', volume_col: str = 'volume') -> Dict:
        """
        Validate a DataFrame for common data quality issues.
        
        Args:
            df: DataFrame to validate
            price_col: Name of price column
            volume_col: Name of volume column
        
        Returns:
            Dict with validation results
        """
        issues = []
        warnings = []
        
        total_rows = len(df)
        if total_rows == 0:
            return {
                'valid': False,
                'issues': ['Empty DataFrame'],
                'warnings': [],
                'missing_ratio': 1.0,
                'stats': {}
            }
        
        stats = {
            'total_rows': total_rows,
            'unique_tickers': df['ticker'].nunique() if 'ticker' in df.columns else 0
        }
        
        # Check for zero prices
        if price_col in df.columns:
            zero_prices = (df[price_col] == 0).sum()
            if zero_prices > 0:
                issues.append(f"Zero prices: {zero_prices} rows ({zero_prices/total_rows*100:.1f}%)")
            stats['zero_prices'] = int(zero_prices)
        
        # Check for NaN values in critical columns
        nan_counts = {}
        for col in [price_col, volume_col, 'ticker', 'date']:
            if col in df.columns:
                nan_count = df[col].isna().sum()
                if nan_count > 0:
                    nan_counts[col] = int(nan_count)
                    if col in [price_col, 'ticker']:
                        issues.append(f"NaN in {col}: {nan_count} rows")
                    else:
                        warnings.append(f"NaN in {col}: {nan_count} rows")
        
        stats['nan_counts'] = nan_counts
        
        # Check for extreme values (price > 100000 or < 0)
        if price_col in df.columns:
            extreme_high = (df[price_col] > 100000).sum()
            extreme_low = (df[price_col] < 0).sum()
            if extreme_high > 0:
                warnings.append(f"Extreme high prices (>100k): {extreme_high}")
            if extreme_low > 0:
                issues.append(f"Negative prices: {extreme_low}")
        
        # Calculate missing ratio
        critical_cols = [c for c in [price_col, 'ticker'] if c in df.columns]
        if critical_cols:
            missing_ratio = df[critical_cols].isna().any(axis=1).sum() / total_rows
        else:
            missing_ratio = 0.0
        
        return {
            'valid': len(issues) == 0,
            'issues': issues,
            'warnings': warnings,
            'missing_ratio': round(missing_ratio, 4),
            'stats': stats
        }
    
    @staticmethod
    def validate_json_data(data: Dict, required_fields: List[str] = None) -> Dict:
        """
        Validate JSON/dict data structure.
        
        Args:
            data: Dict to validate
            required_fields: List of required top-level keys
        
        Returns:
            Dict with validation results
        """
        issues = []
        warnings = []
        
        if not isinstance(data, dict):
            return {
                'valid': False,
                'issues': ['Data is not a dictionary'],
                'warnings': []
            }
        
        # Check required fields
        if required_fields:
            for field in required_fields:
                if field not in data:
                    issues.append(f"Missing required field: {field}")
        
        # Check for empty values
        empty_fields = [k for k, v in data.items() if v is None or v == '' or v == []]
        if empty_fields:
            warnings.append(f"Empty fields: {', '.join(empty_fields)}")
        
        return {
            'valid': len(issues) == 0,
            'issues': issues,
            'warnings': warnings
        }


class DataQualityLogger:
    """Log and track data quality metrics over time"""
    
    def __init__(self, log_dir: str = '.'):
        self.log_dir = log_dir
        self.log_file = os.path.join(log_dir, 'data_quality_log.json')
    
    def log_fetch(self, source: str, success: bool, row_count: int = None, issues: List[str] = None):
        """Log a data fetch attempt"""
        entry = {
            'timestamp': datetime.now().isoformat(),
            'source': source,
            'success': success,
            'row_count': row_count,
            'issues': issues or []
        }
        
        # Append to log file
        logs = []
        if os.path.exists(self.log_file):
            try:
                with open(self.log_file, 'r') as f:
                    logs = json.load(f)
            except:
                logs = []
        
        logs.append(entry)
        
        # Keep only last 100 entries
        logs = logs[-100:]
        
        with open(self.log_file, 'w') as f:
            json.dump(logs, f, indent=2)
    
    def get_recent_issues(self, limit: int = 10) -> List[Dict]:
        """Get recent data quality issues"""
        if not os.path.exists(self.log_file):
            return []
        
        try:
            with open(self.log_file, 'r') as f:
                logs = json.load(f)
            
            # Filter entries with issues
            issues = [log for log in logs if log.get('issues')]
            return issues[-limit:]
        except:
            return []


def add_quality_metadata(output_data: Dict, source: str, validation_result: Dict = None) -> Dict:
    """
    Convenience function to add quality metadata to output.
    
    Args:
        output_data: The data to wrap
        source: Source identifier
        validation_result: Optional validation results to include
    
    Returns:
        Wrapped data with metadata
    """
    data_quality = 'actual'
    notes = None
    
    if validation_result:
        if not validation_result.get('valid', True):
            data_quality = 'partial'
            notes = '; '.join(validation_result.get('issues', []))
        elif validation_result.get('warnings'):
            notes = '; '.join(validation_result.get('warnings', []))
    
    return DataQualityWrapper.wrap_output(
        data=output_data,
        source=source,
        data_quality=data_quality,
        notes=notes
    )


# Standalone helper for quick validation
def quick_validate(df: pd.DataFrame) -> bool:
    """Quick validation - returns True if data seems OK"""
    result = DataQualityWrapper.validate_dataframe(df)
    return result['valid']
