# 🤖 Logwatch AI Analyzer

AIを使用してlogwatch出力を分析し、重要な問題のみをメール通知するシステムです。

## 📋 概要

従来のlogwatchは毎日大量のログをメール送信しますが、Logwatch AIは：
- OpenAI APIを使用してログを智能的に分析
- セキュリティ問題やシステム異常のみを検出
- 重要度に応じて通知の有無を判定
- HTMLフォーマットで読みやすいレポートを送信

## 🎯 主な機能

### AIによる智能的な分析
- SSH攻撃、ディスク使用率、サービスエラーを評価
- 通常のfail2banブロックと実際の脅威を区別
- 重要度を5段階で判定（none/low/medium/high/critical）

### カスタマイズ可能な通知
- しきい値設定で通知レベルを調整
- 複数の宛先メールアドレスに対応
- HTML/プレーンテキスト両対応

### 無視される通常イベント
- fail2banによる通常のブロック（1000件/日未満）
- mod_proxyの少量接続試行（50件/日未満）
- ディスク使用率80%未満
- 定期的なcronジョブ実行

### アラート対象の重要イベント
- 大量SSH攻撃（1000件/日以上）
- ディスク使用率80%超過
- サービスクラッシュ
- 不正アクセス成功の可能性
- データベースエラー

## 💵 コスト

OpenAI GPT-4o-mini使用時の概算：
- 1日1回の分析: 約$0.001-0.003
- 月額: 約$0.03-0.09（約3-10円）

## 🛡️ セーフティ機能（API過剰利用防止）

### レート制限
- **時間あたり制限**: 10リクエスト/時（デフォルト）
- **日次制限**: 50リクエスト/日（デフォルト）
- **最小実行間隔**: 5分間
- **同時実行防止**: ファイルロックで重複起動をブロック

### リトライ機能
- **自動リトライ**: 最大3回（指数バックオフ）
- **タイムアウト**: 30秒/リクエスト
- **エラー時の待機**: 30秒、60秒、120秒と段階的に増加

### 保護機能の動作
1. 5分以内の連続実行を拒否
2. 1時間に10回を超えるAPIコールをブロック
3. 1日50回の上限に到達したら停止
4. 同時に複数のインスタンスが起動しないようロック

## 📦 インストール

### 前提条件
- Python 3.6以上
- logwatchインストール済み
- OpenAI APIキー

### 自動インストール

```bash
# リポジトリをクローン
git clone https://github.com/yourusername/logwatch-ai.git
cd logwatch-ai

# セットアップスクリプトを実行
sudo bash setup.sh
```

### 手動インストール

1. **依存関係のインストール**
```bash
pip3 install openai
```

2. **設定ファイルの作成**
```bash
sudo mkdir -p /etc/logwatch-ai
sudo cp config.example.json /etc/logwatch-ai/config.json
sudo nano /etc/logwatch-ai/config.json
```

3. **OpenAI APIキーの設定**
```json
{
    "openai_api_key": "sk-proj-YOUR_ACTUAL_API_KEY",
    "to_emails": ["your-email@example.com"]
}
```

4. **スクリプトのインストール**
```bash
sudo mkdir -p /opt/logwatch-ai
sudo cp logwatch_ai.py /opt/logwatch-ai/logwatch-ai.py
sudo chmod +x /opt/logwatch-ai/logwatch-ai.py
sudo ln -s /opt/logwatch-ai/logwatch-ai.py /usr/local/bin/logwatch-ai
```

5. **Cronジョブの設定**
```bash
sudo cp logwatch-ai.cron /etc/cron.d/logwatch-ai
```

### インストール後のファイル配置

インストールが完了すると、以下のようにファイルが配置されます：

```
/opt/logwatch-ai/
├── logwatch-ai.py                    # メインスクリプト

/etc/logwatch-ai/
├── config.json                        # 設定ファイル

/etc/cron.d/
├── logwatch-ai                        # Cronジョブ設定

/usr/local/bin/
├── logwatch-ai                        # シンボリックリンク → /opt/logwatch-ai/logwatch-ai.py

/var/log/
├── logwatch-ai.log                    # 実行ログ
├── logwatch-ai-analysis.json          # 最新の分析結果
├── logwatch_output.txt                # logwatch出力（デバッグ用）
└── logwatch-ai-ratelimit.json         # レート制限データ
```

## ⚙️ 設定

### config.json パラメータ

| パラメータ | 説明 | デフォルト |
|-----------|------|------------|
| `openai_api_key` | OpenAI APIキー | 必須 |
| `openai_model` | 使用するAIモデル | gpt-4o-mini |
| `alert_threshold` | 通知しきい値 | medium |
| `always_send_summary` | 常に日次レポートを送信 | false |
| `to_emails` | 送信先メールアドレス | ["root@localhost"] |
| `smtp_host` | SMTPサーバー | localhost |
| `smtp_port` | SMTPポート | 25 |
| **レート制限設定** | | |
| `max_requests_per_hour` | 1時間あたりの最大リクエスト数 | 10 |
| `max_requests_per_day` | 1日あたりの最大リクエスト数 | 50 |
| `min_interval_minutes` | 最小実行間隔（分） | 5 |
| `max_retries` | API失敗時の最大リトライ回数 | 3 |
| `retry_delay_seconds` | リトライ時の初期待機時間（秒） | 30 |

### しきい値レベル

- `none`: 通知なし
- `low`: 低レベル以上で通知
- `medium`: 中レベル以上で通知（推奨）
- `high`: 高レベル以上で通知
- `critical`: 緊急時のみ通知

## 🚀 使用方法

### 手動実行
```bash
sudo logwatch-ai
```

### ログの確認
```bash
# リアルタイムログ監視
tail -f /var/log/logwatch-ai.log

# 最新の分析結果を確認
cat /var/log/logwatch-ai-analysis.json | jq
```

### 設定変更
```bash
sudo nano /etc/logwatch-ai/config.json
```

## 📊 出力例

### 正常時（通知なし）
```json
{
    "severity": "none",
    "issues_found": false,
    "summary": "システムは正常に動作しています",
    "statistics": {
        "ssh_attempts": 45,
        "blocked_ips": 12,
        "disk_usage_percent": 47
    }
}
```

### 異常検出時（メール通知）
```
🔴 LOGWATCH AI ANALYSIS - 2024-12-19 07:00:00
===========================================================
Severity: HIGH
Summary: 大量のSSH攻撃と高いディスク使用率を検出

CRITICAL ISSUES:
  • SSH攻撃が1,234回/日（しきい値を超過）
  • ディスク使用率が85%に到達

RECOMMENDATIONS:
  • fail2banの設定を強化
  • 不要なファイルを削除してディスク容量を確保
```

## 🔧 トラブルシューティング

### APIキーエラー
```bash
# 設定ファイルを確認
sudo nano /etc/logwatch-ai/config.json
# openai_api_keyが正しく設定されているか確認
```

### メールが届かない
```bash
# SMTPサーバーの設定を確認
sudo nano /etc/logwatch-ai/config.json
# smtp_host, smtp_portを確認

# テスト送信
echo "Test" | mail -s "Test" your-email@example.com
```

### ログが生成されない
```bash
# logwatchが正常に動作しているか確認
sudo logwatch --output stdout

# cronジョブを確認
sudo systemctl status cron
cat /etc/cron.d/logwatch-ai
```

## 📝 カスタマイズ

### AI分析ロジックの調整

`/opt/logwatch-ai/logwatch-ai.py`の`analyze_with_ai`メソッド内のプロンプトを編集：

```python
# より厳格な判定基準に変更
prompt = f"""
Alert on these critical issues:
- SSH attacks over 500/day  # 1000から500に変更
- Disk usage over 70%       # 80%から70%に変更
...
"""
```

### 通知フォーマットの変更

`format_email_body`メソッドをカスタマイズして、独自のレポート形式を作成できます。

## 🔒 セキュリティ

- APIキーは`/etc/logwatch-ai/config.json`に保存（権限600）
- ログファイルは定期的にローテーション
- 機密情報はログに出力されません

## 📄 ライセンス

**Logwatch AI License** - カスタムライセンス

著作権 (c) 2025 いつもの匠（ヤマネックス非公開株式会社） / itumonotakumi (Yamanex Private Co., Ltd.)

### 許可される行為
- ✅ 個人利用・商用利用（社内業務での使用）
- ✅ ソフトウェアの改変（個人・社内利用目的）
- ✅ オリジナルソフトウェアの無償配布

### 許可されない行為
- ❌ ソフトウェアまたはその一部の販売
- ❌ 改変版ソフトウェアの販売
- ❌ 商業的利益を目的とした配布

詳細は [LICENSE](LICENSE) ファイルをご確認ください。

## 🤝 貢献

プルリクエスト歓迎です！
1. Fork the repository
2. Create your feature branch
3. Commit your changes
4. Push to the branch
5. Open a Pull Request

## 💬 サポート

問題が発生した場合は、GitHubのIssueで報告してください。