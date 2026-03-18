#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Notifier - Telegram/Slack notifications for trading signals and events.

Features:
1. Telegram bot integration
2. Signal notifications
3. Gate change alerts
4. Daily summaries
"""
import os
import json
import logging
from dataclasses import dataclass
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)


def load_env():
    """Load environment variables"""
    try:
        from dotenv import load_dotenv
        env_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
        if os.path.exists(env_path):
            load_dotenv(env_path)
        else:
            load_dotenv()
    except ImportError:
        pass


@dataclass
class NotificationConfig:
    """Notification configuration"""
    telegram_token: str = ""
    telegram_chat_id: str = ""
    slack_webhook: str = ""
    enabled: bool = True
    
    @classmethod
    def from_env(cls) -> "NotificationConfig":
        load_env()
        return cls(
            telegram_token=os.environ.get('TELEGRAM_BOT_TOKEN', ''),
            telegram_chat_id=os.environ.get('TELEGRAM_CHAT_ID', ''),
            slack_webhook=os.environ.get('SLACK_WEBHOOK_URL', ''),
            enabled=True
        )


class TelegramNotifier:
    """Telegram notification sender"""
    
    def __init__(self, config: NotificationConfig = None):
        self.config = config or NotificationConfig.from_env()
    
    def is_configured(self) -> bool:
        return bool(self.config.telegram_token and self.config.telegram_chat_id)
    
    def send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        """Send a message via Telegram"""
        if not self.is_configured():
            logger.warning("Telegram not configured")
            return False
        
        try:
            import requests
            
            url = f"https://api.telegram.org/bot{self.config.telegram_token}/sendMessage"
            data = {
                "chat_id": self.config.telegram_chat_id,
                "text": text,
                "parse_mode": parse_mode
            }
            
            response = requests.post(url, json=data, timeout=10)
            return response.status_code == 200
            
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False
    
    def send_signal(
        self,
        symbol: str,
        signal_type: str,
        score: int,
        gate: str,
        price: float = None
    ) -> bool:
        """Send VCP signal notification"""
        gate_emoji = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}.get(gate, "⚪")
        
        message = f"""
🎯 *VCP Signal Alert*

*Symbol*: `{symbol}`
*Type*: {signal_type}
*Score*: {score}/100
*Gate*: {gate_emoji} {gate}
{f'*Price*: ${price:,.2f}' if price else ''}

_Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}_
"""
        return self.send_message(message)
    
    def send_gate_change(self, old_gate: str, new_gate: str, score: int) -> bool:
        """Send gate change notification"""
        new_emoji = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}.get(new_gate, "⚪")
        
        message = f"""
🚦 *Gate Status Change*

{old_gate} → {new_emoji} *{new_gate}*
Score: {score}/100

_Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}_
"""
        return self.send_message(message)
    
    def send_daily_summary(
        self,
        total_trades: int,
        win_rate: float,
        pnl_pct: float,
        gate: str
    ) -> bool:
        """Send daily trading summary"""
        pnl_emoji = "📈" if pnl_pct >= 0 else "📉"
        gate_emoji = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}.get(gate, "⚪")
        
        message = f"""
📊 *Daily Trading Summary*

*Trades*: {total_trades}
*Win Rate*: {win_rate:.1f}%
*P&L*: {pnl_emoji} {pnl_pct:+.2f}%
*Gate*: {gate_emoji} {gate}

_Date: {datetime.now().strftime('%Y-%m-%d')}_
"""
        return self.send_message(message)
    
    def send_risk_alert(self, alert_type: str, message: str) -> bool:
        """Send risk management alert"""
        text = f"""
⚠️ *Risk Alert: {alert_type}*

{message}

_Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}_
"""
        return self.send_message(text)


class Notifier:
    """
    Unified notifier supporting multiple channels.
    """
    
    def __init__(self, config: NotificationConfig = None):
        self.config = config or NotificationConfig.from_env()
        self.telegram = TelegramNotifier(self.config)
    
    def notify(self, message: str, channel: str = "all") -> bool:
        """Send notification to specified channel(s)"""
        success = False
        
        if channel in ["all", "telegram"]:
            if self.telegram.is_configured():
                success = self.telegram.send_message(message) or success
        
        return success
    
    def signal(self, **kwargs) -> bool:
        """Send signal notification"""
        return self.telegram.send_signal(**kwargs)
    
    def gate_change(self, **kwargs) -> bool:
        """Send gate change notification"""
        return self.telegram.send_gate_change(**kwargs)
    
    def daily_summary(self, **kwargs) -> bool:
        """Send daily summary"""
        return self.telegram.send_daily_summary(**kwargs)
    
    def risk_alert(self, **kwargs) -> bool:
        """Send risk alert"""
        return self.telegram.send_risk_alert(**kwargs)


if __name__ == "__main__":
    print("\n📱 NOTIFIER TEST")
    print("=" * 50)
    
    notifier = Notifier()
    
    print(f"\nTelegram configured: {notifier.telegram.is_configured()}")
    
    if notifier.telegram.is_configured():
        print("\n📤 Sending test message...")
        success = notifier.telegram.send_message("🧪 Test message from VCP System")
        print(f"   Result: {'✅ Sent' if success else '❌ Failed'}")
    else:
        print("\n⚠️ Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")
    
    print("\n✅ Notifier test complete!")
