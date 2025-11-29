#!/usr/bin/env python3
"""
Logwatch AI Analyzer
Analyzes logwatch output using OpenAI API and sends alerts only when issues are detected
"""

import os
import json
import subprocess
import logging
import smtplib
import time
import fcntl
import socket
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

try:
    from openai import OpenAI
except ImportError:
    print("Error: OpenAI library not installed. Run: pip install openai")
    exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/var/log/logwatch-ai.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class LogwatchAIAnalyzer:
    """Analyzes logwatch output using AI and sends notifications"""

    def __init__(self, config_path: str = "/etc/logwatch-ai/config.json"):
        """Initialize with configuration"""
        self.config = self.load_config(config_path)
        self.client = OpenAI(api_key=self.config['openai_api_key'])
        self.rate_limit_file = Path('/var/log/logwatch-ai-ratelimit.json')
        self.lock_file = Path('/var/lock/logwatch-ai.lock')

    def load_config(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from JSON file"""
        config_file = Path(config_path)

        # Default configuration
        default_config = {
            "openai_api_key": os.getenv("OPENAI_API_KEY", ""),
            "openai_model": "gpt-4o-mini",
            "smtp_host": "localhost",
            "smtp_port": 25,
            "smtp_user": "",
            "smtp_password": "",
            "smtp_use_tls": False,
            "from_email": "logwatch-ai@localhost",
            "to_emails": ["root@localhost"],
            "alert_threshold": "medium",
            "logwatch_output_file": "/var/log/logwatch_output.txt",
            "always_send_summary": False,
            "max_requests_per_hour": 10,
            "max_requests_per_day": 50,
            "min_interval_minutes": 5,
            "max_retries": 3,
            "retry_delay_seconds": 30
        }

        if config_file.exists():
            try:
                with open(config_file, 'r') as f:
                    user_config = json.load(f)
                    default_config.update(user_config)
            except Exception as e:
                logger.warning(f"Failed to load config from {config_path}: {e}")

        return default_config

    def run_logwatch(self) -> str:
        """Execute logwatch and capture output"""
        try:
            result = subprocess.run(
                ['/usr/sbin/logwatch', '--output', 'stdout', '--format', 'text',
                 '--range', 'yesterday', '--detail', '10'],
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode != 0:
                logger.error(f"Logwatch failed with code {result.returncode}: {result.stderr}")
                return ""

            # Save raw output for debugging
            output_file = Path(self.config['logwatch_output_file'])
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(result.stdout)

            return result.stdout

        except Exception as e:
            logger.error(f"Failed to run logwatch: {e}")
            return ""

    def check_rate_limits(self) -> bool:
        """Check if we're within rate limits to prevent API abuse"""
        now = datetime.now()

        # Load existing rate limit data
        rate_data = {"requests": []}
        if self.rate_limit_file.exists():
            try:
                with open(self.rate_limit_file, 'r') as f:
                    rate_data = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load rate limit data: {e}")

        # Clean up old entries (older than 24 hours)
        cutoff_time = (now - timedelta(days=1)).isoformat()
        rate_data["requests"] = [
            req for req in rate_data["requests"]
            if req > cutoff_time
        ]

        # Check minimum interval since last request
        if rate_data["requests"]:
            last_request = datetime.fromisoformat(rate_data["requests"][-1])
            time_since_last = (now - last_request).total_seconds() / 60

            if time_since_last < self.config["min_interval_minutes"]:
                remaining = self.config["min_interval_minutes"] - time_since_last
                logger.warning(f"Rate limit: minimum interval not met. Wait {remaining:.1f} more minutes.")
                return False

        # Check hourly limit
        hour_ago = (now - timedelta(hours=1)).isoformat()
        hour_requests = sum(1 for req in rate_data["requests"] if req > hour_ago)

        if hour_requests >= self.config["max_requests_per_hour"]:
            logger.warning(f"Rate limit: hourly limit ({self.config['max_requests_per_hour']}) reached")
            return False

        # Check daily limit
        day_requests = len(rate_data["requests"])

        if day_requests >= self.config["max_requests_per_day"]:
            logger.warning(f"Rate limit: daily limit ({self.config['max_requests_per_day']}) reached")
            return False

        # Add current request to rate limit data
        rate_data["requests"].append(now.isoformat())

        # Save updated rate limit data
        try:
            self.rate_limit_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.rate_limit_file, 'w') as f:
                json.dump(rate_data, f)
        except Exception as e:
            logger.error(f"Failed to save rate limit data: {e}")

        return True

    def acquire_lock(self) -> Optional[Any]:
        """Acquire a file lock to prevent concurrent runs"""
        try:
            self.lock_file.parent.mkdir(parents=True, exist_ok=True)
            lock_fd = open(self.lock_file, 'w')
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return lock_fd
        except (IOError, OSError):
            logger.error("Another instance is already running. Exiting to prevent duplicate API calls.")
            return None

    def release_lock(self, lock_fd):
        """Release the file lock"""
        if lock_fd:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                lock_fd.close()
            except Exception as e:
                logger.warning(f"Failed to release lock: {e}")

    def analyze_with_ai(self, log_content: str) -> Dict[str, Any]:
        """Analyze log content using OpenAI API with rate limiting and retries"""

        if not log_content:
            return {
                "severity": "error",
                "issues_found": True,
                "summary": "分析するlogwatch出力がありません",
                "details": [],
                "recommendations": []
            }

        # Check rate limits before making API call
        if not self.check_rate_limits():
            return {
                "severity": "error",
                "issues_found": True,
                "summary": "レート制限超過 - API過剰利用防止のためスキップしました",
                "critical_issues": ["レート制限保護が作動しました"],
                "warnings": [],
                "statistics": {},
                "recommendations": ["次回実行まで待つか、設定でレート制限を調整してください"]
            }

        prompt = f"""あなたはLinuxシステムセキュリティの専門家です。以下のlogwatch出力を分析し、構造化された評価を日本語で提供してください。

【最重要】本当に対応が必要な問題だけを報告してください。インターネット公開サーバーで日常的に発生する事象は全て無視してください。

以下は【完全に無視】してください（critical_issuesやwarningsに含めない）：
- 失敗したSSHログイン試行（ブロック済みの攻撃）
- 404/400/401エラーを返したHTTPリクエスト（スキャンボットは日常的）
- /.env、/.git/config、/phpMyAdmin等への脆弱性スキャン（全て失敗している）
- "Attempts to use known hacks"の報告（攻撃試行は失敗している）
- mod_proxyへの接続試行
- fail2banによるブロック
- ディスク使用率85%未満
- 通常のサービス再起動
- 定期的なcronジョブ実行
- パッケージの更新・インストール
- 通常のメール送受信

以下の【本当に重大な問題のみ】をcritical_issuesに含めてください：
- 認証成功後の不審なアクティビティ（ログイン成功+異常操作）
- rootや管理者での予期しないログイン成功
- ディスク使用率85%超過
- サービスの異常停止・クラッシュ（再起動ではなく停止）
- カーネルパニックやOOMキラー発動
- データベースの破損やクラッシュ
- ファイルシステムエラー

severity判定基準：
- "none": 問題なし（日常的なスキャンのみ）
- "low": 軽微な注意事項のみ
- "medium": 確認が必要だが緊急ではない
- "high": 24時間以内の対応が必要
- "critical": 即時対応が必要

JSON形式で日本語で回答してください：
{{
    "severity": "none|low|medium|high|critical",
    "issues_found": true|false,
    "summary": "簡潔な一行サマリー",
    "critical_issues": ["問題1", "問題2"],
    "warnings": ["警告1", "警告2"],
    "statistics": {{
        "ssh_attempts": 数値,
        "blocked_ips": 数値,
        "disk_usage_percent": 数値,
        "errors_count": 数値
    }},
    "recommendations": ["推奨アクション1", "推奨アクション2"]
}}

Logwatch出力:
{log_content[:8000]}"""  # Limit to avoid token limits

        # Retry logic with exponential backoff
        last_error = None
        for attempt in range(self.config['max_retries']):
            try:
                response = self.client.chat.completions.create(
                    model=self.config['openai_model'],
                    messages=[
                        {"role": "system", "content": "あなたはLinuxセキュリティの専門家です。簡潔で実用的な分析を日本語で提供してください。"},
                        {"role": "user", "content": prompt}
                    ],
                    # temperature=0,  # Removed - not supported by gpt-4o-mini
                    max_completion_tokens=1000,  # Changed from max_tokens to max_completion_tokens
                    response_format={"type": "json_object"},
                    timeout=30  # 30 second timeout per request
                )

                result = json.loads(response.choices[0].message.content)
                logger.info(f"AI Analysis complete. Severity: {result.get('severity', 'unknown')}")
                return result

            except Exception as e:
                last_error = e
                logger.warning(f"API call attempt {attempt + 1}/{self.config['max_retries']} failed: {e}")

                if attempt < self.config['max_retries'] - 1:
                    delay = self.config['retry_delay_seconds'] * (2 ** attempt)  # Exponential backoff
                    logger.info(f"Retrying in {delay} seconds...")
                    time.sleep(delay)

        # All retries failed
        logger.error(f"All API retry attempts failed. Last error: {last_error}")
        return {
            "severity": "error",
            "issues_found": True,
            "summary": f"AI analysis failed after {self.config['max_retries']} attempts: {str(last_error)}",
            "critical_issues": ["Failed to analyze logs with AI after multiple retries"],
            "warnings": [],
            "statistics": {},
            "recommendations": ["Check OpenAI API key, connectivity, and rate limits"]
        }

    def should_send_alert(self, analysis: Dict[str, Any]) -> bool:
        """Determine if an alert should be sent based on analysis"""
        if self.config['always_send_summary']:
            return True

        severity = analysis.get('severity', 'none')
        threshold = self.config['alert_threshold']

        severity_levels = {
            'none': 0,
            'low': 1,
            'medium': 2,
            'high': 3,
            'critical': 4,
            'error': 4
        }

        return severity_levels.get(severity, 0) >= severity_levels.get(threshold, 2)

    def format_email_body(self, analysis: Dict[str, Any], html: bool = True) -> str:
        """Format analysis results for email"""
        severity = analysis.get('severity', 'unknown').upper()
        severity_ja = {
            'NONE': '正常',
            'LOW': '低',
            'MEDIUM': '中',
            'HIGH': '高',
            'CRITICAL': '緊急',
            'ERROR': 'エラー'
        }
        emoji_map = {
            'NONE': '✅',
            'LOW': '📋',
            'MEDIUM': '⚠️',
            'HIGH': '🔴',
            'CRITICAL': '🚨',
            'ERROR': '❌'
        }
        emoji = emoji_map.get(severity, '❓')
        severity_text = severity_ja.get(severity, severity)
        hostname = socket.gethostname()

        if html:
            body = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: 'Hiragino Sans', 'Yu Gothic', Arial, sans-serif; line-height: 1.6; }}
        .header {{ background: {'#d4edda' if severity == 'NONE' else '#f8d7da' if severity in ['HIGH', 'CRITICAL'] else '#fff3cd'};
                   padding: 15px; border-radius: 5px; margin-bottom: 20px; }}
        .severity {{ font-size: 24px; font-weight: bold; }}
        .section {{ margin: 20px 0; }}
        .issues {{ background: #f8f9fa; padding: 10px; border-left: 4px solid #dc3545; }}
        .warnings {{ background: #f8f9fa; padding: 10px; border-left: 4px solid #ffc107; }}
        .stats {{ background: #e9ecef; padding: 10px; border-radius: 5px; }}
        ul {{ margin: 10px 0; }}
    </style>
</head>
<body>
    <div class="header">
        <div class="severity">{emoji} 重要度: {severity_text}</div>
        <div>ホスト: {hostname}</div>
        <div>日時: {datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')}</div>
    </div>

    <div class="section">
        <h2>📝 概要</h2>
        <p>{analysis.get('summary', '概要情報がありません')}</p>
    </div>
"""

            if analysis.get('critical_issues'):
                body += """
    <div class="section issues">
        <h3>🚨 緊急対応が必要な問題</h3>
        <ul>"""
                for issue in analysis['critical_issues']:
                    body += f"\n            <li>{issue}</li>"
                body += """
        </ul>
    </div>"""

            if analysis.get('warnings'):
                body += """
    <div class="section warnings">
        <h3>⚠️ 警告</h3>
        <ul>"""
                for warning in analysis['warnings']:
                    body += f"\n            <li>{warning}</li>"
                body += """
        </ul>
    </div>"""

            if analysis.get('statistics'):
                body += """
    <div class="section stats">
        <h3>📊 統計情報</h3>
        <ul>"""
                stats_ja = {
                    'ssh_attempts': 'SSH試行回数',
                    'blocked_ips': 'ブロックされたIP数',
                    'disk_usage_percent': 'ディスク使用率(%)',
                    'errors_count': 'エラー数'
                }
                for key, value in analysis['statistics'].items():
                    label = stats_ja.get(key, key.replace('_', ' ').title())
                    body += f"\n            <li><strong>{label}:</strong> {value}</li>"
                body += """
        </ul>
    </div>"""

            if analysis.get('recommendations'):
                body += """
    <div class="section">
        <h3>💡 推奨対応</h3>
        <ul>"""
                for rec in analysis['recommendations']:
                    body += f"\n            <li>{rec}</li>"
                body += """
        </ul>
    </div>"""

            body += """
</body>
</html>"""
        else:
            # Plain text version
            body = f"""{emoji} LOGWATCH AI 分析結果 - {datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')}
{'=' * 60}
ホスト: {hostname}
重要度: {severity_text}
概要: {analysis.get('summary', '概要情報がありません')}

"""
            if analysis.get('critical_issues'):
                body += "🚨 緊急対応が必要な問題:\n"
                for issue in analysis['critical_issues']:
                    body += f"  • {issue}\n"
                body += "\n"

            if analysis.get('warnings'):
                body += "⚠️ 警告:\n"
                for warning in analysis['warnings']:
                    body += f"  • {warning}\n"
                body += "\n"

            if analysis.get('statistics'):
                body += "📊 統計情報:\n"
                stats_ja = {
                    'ssh_attempts': 'SSH試行回数',
                    'blocked_ips': 'ブロックされたIP数',
                    'disk_usage_percent': 'ディスク使用率(%)',
                    'errors_count': 'エラー数'
                }
                for key, value in analysis['statistics'].items():
                    label = stats_ja.get(key, key.replace('_', ' ').title())
                    body += f"  • {label}: {value}\n"
                body += "\n"

            if analysis.get('recommendations'):
                body += "💡 推奨対応:\n"
                for rec in analysis['recommendations']:
                    body += f"  • {rec}\n"

        return body

    def send_email(self, analysis: Dict[str, Any]) -> bool:
        """Send email notification"""
        try:
            severity = analysis.get('severity', 'unknown').upper()
            severity_ja = {
                'NONE': '正常',
                'LOW': '低',
                'MEDIUM': '中',
                'HIGH': '高',
                'CRITICAL': '緊急',
                'ERROR': 'エラー'
            }
            emoji_map = {
                'NONE': '✅',
                'LOW': '📋',
                'MEDIUM': '⚠️',
                'HIGH': '🔴',
                'CRITICAL': '🚨',
                'ERROR': '❌'
            }
            emoji = emoji_map.get(severity, '❓')
            severity_text = severity_ja.get(severity, severity)

            msg = MIMEMultipart('alternative')
            hostname = socket.gethostname()
            msg['Subject'] = f"{emoji} [{hostname}] Logwatch AI レポート - 重要度: {severity_text} - {datetime.now().strftime('%Y年%m月%d日')}"
            msg['From'] = self.config['from_email']
            msg['To'] = ', '.join(self.config['to_emails'])

            # Add both plain text and HTML versions
            text_part = MIMEText(self.format_email_body(analysis, html=False), 'plain')
            html_part = MIMEText(self.format_email_body(analysis, html=True), 'html')

            msg.attach(text_part)
            msg.attach(html_part)

            # Send email
            # Port 465 uses SSL, not STARTTLS
            if self.config['smtp_port'] == 465:
                smtp = smtplib.SMTP_SSL(self.config['smtp_host'], self.config['smtp_port'])
            else:
                smtp = smtplib.SMTP(self.config['smtp_host'], self.config['smtp_port'])
                if self.config['smtp_use_tls']:
                    smtp.starttls()

            if self.config['smtp_user'] and self.config['smtp_password']:
                smtp.login(self.config['smtp_user'], self.config['smtp_password'])

            smtp.send_message(msg)
            smtp.quit()

            logger.info(f"Email sent successfully to {self.config['to_emails']}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False

    def run(self) -> None:
        """Main execution method with concurrency protection"""
        logger.info("Starting Logwatch AI analysis")

        # Acquire lock to prevent concurrent runs
        lock_fd = self.acquire_lock()
        if not lock_fd:
            logger.error("Could not acquire lock - another instance may be running")
            return

        try:
            # Run logwatch
            logger.info("Running logwatch...")
            log_content = self.run_logwatch()

            if not log_content:
                logger.error("No logwatch output to analyze")
                return

            # Analyze with AI
            logger.info("Analyzing logs with AI...")
            analysis = self.analyze_with_ai(log_content)

            # Save analysis results
            analysis_file = Path('/var/log/logwatch-ai-analysis.json')
            analysis_file.write_text(json.dumps(analysis, indent=2))

            # Send alert if needed
            if self.should_send_alert(analysis):
                logger.info(f"Sending alert email (severity: {analysis.get('severity', 'unknown')})")
                self.send_email(analysis)
            else:
                logger.info(f"No alert needed (severity: {analysis.get('severity', 'unknown')})")

            logger.info("Logwatch AI analysis complete")

        finally:
            # Always release lock
            self.release_lock(lock_fd)

def main():
    """Main entry point"""
    try:
        analyzer = LogwatchAIAnalyzer()
        analyzer.run()
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        exit(1)

if __name__ == "__main__":
    main()