#!/bin/bash
#
# Logwatch AI Setup Script
# Installs and configures Logwatch AI analyzer
#

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Installation directories
INSTALL_DIR="/opt/logwatch-ai"
CONFIG_DIR="/etc/logwatch-ai"
LOG_DIR="/var/log"
VENV_DIR="$INSTALL_DIR/venv"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}     Logwatch AI Setup Script          ${NC}"
echo -e "${GREEN}========================================${NC}"
echo

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Error: This script must be run as root${NC}"
    exit 1
fi

# Check Python version
echo -e "${YELLOW}Checking Python version...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python 3 is not installed${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
echo "Found Python version: $PYTHON_VERSION"

# Check if logwatch is installed
echo -e "${YELLOW}Checking for logwatch...${NC}"
if ! command -v logwatch &> /dev/null; then
    echo -e "${RED}Error: logwatch is not installed${NC}"
    echo "Install with: apt-get install logwatch (Debian/Ubuntu) or yum install logwatch (RHEL/CentOS)"
    exit 1
fi
echo "logwatch is installed"

# Create virtual environment and install Python dependencies
echo -e "${YELLOW}Creating virtual environment...${NC}"
mkdir -p "$INSTALL_DIR"
python3 -m venv "$VENV_DIR"
echo "Virtual environment created at $VENV_DIR"

echo -e "${YELLOW}Installing Python dependencies...${NC}"
"$VENV_DIR/bin/pip" install --upgrade pip --quiet
"$VENV_DIR/bin/pip" install openai requests --quiet
echo "Dependencies installed"

# Create configuration directory
echo -e "${YELLOW}Creating configuration directory...${NC}"
mkdir -p "$CONFIG_DIR"

# Get OpenAI API key
echo
echo -e "${YELLOW}OpenAI API Configuration${NC}"
echo "Please enter your OpenAI API key (will be stored in config):"
read -s OPENAI_API_KEY
echo

if [ -z "$OPENAI_API_KEY" ]; then
    echo -e "${RED}Warning: No API key provided. You'll need to add it to the config file later.${NC}"
    OPENAI_API_KEY="YOUR_API_KEY_HERE"
fi

# Get email configuration
echo -e "${YELLOW}Email Configuration${NC}"
echo "Enter email address to send alerts to (default: root@localhost):"
read TO_EMAIL
TO_EMAIL=${TO_EMAIL:-root@localhost}

echo "Enter email address to send from (default: logwatch-ai@localhost):"
read FROM_EMAIL
FROM_EMAIL=${FROM_EMAIL:-logwatch-ai@localhost}

echo "Enter SMTP server (default: localhost):"
read SMTP_HOST
SMTP_HOST=${SMTP_HOST:-localhost}

echo "Enter SMTP port (default: 25):"
read SMTP_PORT
SMTP_PORT=${SMTP_PORT:-25}

echo "Use TLS for SMTP? (y/n, default: n):"
read USE_TLS
if [[ "$USE_TLS" == "y" || "$USE_TLS" == "Y" ]]; then
    USE_TLS="true"
else
    USE_TLS="false"
fi

echo "Enter alert threshold (none/low/medium/high/critical, default: medium):"
read ALERT_THRESHOLD
ALERT_THRESHOLD=${ALERT_THRESHOLD:-medium}

echo "Always send daily summary even if no issues? (y/n, default: n):"
read ALWAYS_SEND
if [[ "$ALWAYS_SEND" == "y" || "$ALWAYS_SEND" == "Y" ]]; then
    ALWAYS_SEND="true"
else
    ALWAYS_SEND="false"
fi

# Create configuration file
echo -e "${YELLOW}Creating configuration file...${NC}"
cat > "$CONFIG_DIR/config.json" << EOF
{
    "openai_api_key": "$OPENAI_API_KEY",
    "openai_model": "gpt-4o-mini",
    "smtp_host": "$SMTP_HOST",
    "smtp_port": $SMTP_PORT,
    "smtp_user": "",
    "smtp_password": "",
    "smtp_use_tls": $USE_TLS,
    "from_email": "$FROM_EMAIL",
    "to_emails": ["$TO_EMAIL"],
    "alert_threshold": "$ALERT_THRESHOLD",
    "logwatch_output_file": "/var/log/logwatch_output.txt",
    "always_send_summary": $ALWAYS_SEND
}
EOF

chmod 600 "$CONFIG_DIR/config.json"
echo "Configuration saved to $CONFIG_DIR/config.json"

# Install the main script
echo -e "${YELLOW}Installing Logwatch AI script...${NC}"
mkdir -p "$INSTALL_DIR"
cp logwatch_ai.py "$INSTALL_DIR/logwatch-ai.py"
chmod +x "$INSTALL_DIR/logwatch-ai.py"

# Create wrapper script in /usr/local/bin for convenience
cat > /usr/local/bin/logwatch-ai << 'WRAPPER'
#!/bin/bash
exec /opt/logwatch-ai/venv/bin/python /opt/logwatch-ai/logwatch-ai.py "$@"
WRAPPER
chmod +x /usr/local/bin/logwatch-ai
echo "Script installed to $INSTALL_DIR/logwatch-ai.py"
echo "Wrapper script created at /usr/local/bin/logwatch-ai"

# Create cron job
echo -e "${YELLOW}Setting up cron job...${NC}"
CRON_FILE="/etc/cron.d/logwatch-ai"
cat > "$CRON_FILE" << EOF
# Logwatch AI Analyzer
# Runs daily at 7:00 AM
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin

0 7 * * * root /opt/logwatch-ai/venv/bin/python /opt/logwatch-ai/logwatch-ai.py >> /var/log/logwatch-ai.log 2>&1
EOF

chmod 644 "$CRON_FILE"
echo "Cron job created at $CRON_FILE"

# Disable original logwatch email if exists
echo -e "${YELLOW}Checking for existing logwatch cron job...${NC}"
if [ -f "/etc/cron.daily/00logwatch" ]; then
    echo "Found /etc/cron.daily/00logwatch"
    echo "Do you want to disable the original logwatch email? (y/n):"
    read DISABLE_ORIGINAL
    if [[ "$DISABLE_ORIGINAL" == "y" || "$DISABLE_ORIGINAL" == "Y" ]]; then
        mv /etc/cron.daily/00logwatch /etc/cron.daily/00logwatch.disabled
        echo "Original logwatch cron job disabled (backed up as 00logwatch.disabled)"
    fi
fi

# Create log rotation configuration
echo -e "${YELLOW}Setting up log rotation...${NC}"
cat > /etc/logrotate.d/logwatch-ai << EOF
/var/log/logwatch-ai.log {
    weekly
    rotate 4
    compress
    missingok
    notifempty
}

/var/log/logwatch_output.txt {
    daily
    rotate 7
    compress
    missingok
    notifempty
}

/var/log/logwatch-ai-analysis.json {
    daily
    rotate 7
    compress
    missingok
    notifempty
}
EOF
echo "Log rotation configured"

# Test the installation
echo
echo -e "${YELLOW}Testing installation...${NC}"
echo "Running a test analysis (this may take a moment)..."

if /opt/logwatch-ai/venv/bin/python /opt/logwatch-ai/logwatch-ai.py; then
    echo -e "${GREEN}✓ Test successful!${NC}"
else
    echo -e "${RED}✗ Test failed. Please check the logs at /var/log/logwatch-ai.log${NC}"
    exit 1
fi

echo
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}     Installation Complete!             ${NC}"
echo -e "${GREEN}========================================${NC}"
echo
echo "Logwatch AI has been successfully installed!"
echo
echo "Installation directory: $INSTALL_DIR"
echo "Virtual environment: $VENV_DIR"
echo "Configuration file: $CONFIG_DIR/config.json"
echo "Main script: $INSTALL_DIR/logwatch-ai.py"
echo "Wrapper script: /usr/local/bin/logwatch-ai"
echo "Cron job: $CRON_FILE"
echo "Log file: /var/log/logwatch-ai.log"
echo
echo "The system will analyze logs daily at 7:00 AM and send alerts based on your threshold setting."
echo
echo "To manually run the analyzer: logwatch-ai (または $INSTALL_DIR/logwatch-ai.py)"
echo "To edit configuration: nano $CONFIG_DIR/config.json"
echo "To check logs: tail -f /var/log/logwatch-ai.log"
echo
echo -e "${YELLOW}Important: Remember to keep your OpenAI API key secure!${NC}"