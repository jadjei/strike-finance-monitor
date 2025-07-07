#!/bin/bash

# Strike Finance Monitor - Simple Podman Deployment

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
CONTAINER_NAME="strike-finance-monitor"
IMAGE_NAME="strike-monitor"
PORT="5000"

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

check_podman() {
    log_info "Checking Podman installation..."
    
    if ! command -v podman &> /dev/null; then
        log_error "Podman is not installed"
        echo "Install with: sudo dnf install podman"
        exit 1
    fi
    
    # Enable podman socket for user
    systemctl --user enable --now podman.socket 2>/dev/null || true
    
    log_success "Podman is available"
}

setup_firewall() {
    log_info "Configuring firewall for port ${PORT}..."
    
    if sudo systemctl is-active --quiet firewalld; then
        sudo firewall-cmd --permanent --add-port=${PORT}/tcp
        sudo firewall-cmd --reload
        log_success "Firewall configured"
    else
        log_warning "Firewalld not active - ensure port ${PORT} is accessible"
    fi
}

create_config() {
    if [[ ! -f "config.json" ]]; then
        if [[ -f "config.json.template" ]]; then
            log_info "Creating config.json from template..."
            cp config.json.template config.json
            log_warning "Edit config.json with your credentials before starting!"
        else
            log_error "No config.json.template found"
            exit 1
        fi
    else
        log_success "Using existing config.json"
    fi
}

deploy_container() {
    log_info "Deploying Strike Finance Monitor..."
    
    # Build image
    log_info "Building container image..."
    podman build -t ${IMAGE_NAME} .
    
    # Stop and remove existing container
    podman stop ${CONTAINER_NAME} 2>/dev/null || true
    podman rm ${CONTAINER_NAME} 2>/dev/null || true
    
    # Create volumes for persistence
    podman volume create strike-logs 2>/dev/null || true
    podman volume create strike-db 2>/dev/null || true
    
    # Run container (config will be created inside container)
    podman run -d \
        --name ${CONTAINER_NAME} \
        --restart unless-stopped \
        -p ${PORT}:5000 \
        -v strike-logs:/app/logs \
        -v strike-db:/app/db \
        -e TZ=Europe/London \
        --security-opt no-new-privileges \
        --cap-drop ALL \
        --cap-add NET_ADMIN \
        ${IMAGE_NAME}
    
    log_success "Container deployed successfully"
}

setup_systemd_user() {
    log_info "Setting up systemd user service..."
    
    # Create user systemd directory
    mkdir -p ~/.config/systemd/user
    
    # Generate systemd service
    cat > ~/.config/systemd/user/strike-monitor.service << EOF
[Unit]
Description=Strike Finance Monitor Container
After=network.target

[Service]
Type=forking
RemainAfterExit=yes
ExecStart=/usr/bin/podman start ${CONTAINER_NAME}
ExecStop=/usr/bin/podman stop ${CONTAINER_NAME}
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
EOF

    # Enable and start service
    systemctl --user daemon-reload
    systemctl --user enable strike-monitor.service
    systemctl --user start strike-monitor.service
    
    # Enable lingering for user services
    sudo loginctl enable-linger $(whoami)
    
    log_success "Systemd user service configured"
}

show_status() {
    log_info "Checking deployment status..."
    
    if podman ps --format "table {{.Names}} {{.Status}} {{.Ports}}" | grep -q ${CONTAINER_NAME}; then
        log_success "Container is running"
        podman ps --filter name=${CONTAINER_NAME}
    else
        log_error "Container is not running"
    fi
    
    echo ""
    log_info "Recent logs:"
    podman logs --tail 10 ${CONTAINER_NAME}
}

show_completion() {
    local server_ip
    server_ip=$(hostname -I | awk '{print $1}' || echo "localhost")
    
    echo ""
    log_success "Strike Finance Monitor deployed!"
    echo ""
    echo -e "${BLUE}🐋 Container Info:${NC}"
    echo "  Name: ${CONTAINER_NAME}"
    echo "  Dashboard: http://${server_ip}:${PORT}"
    echo ""
    echo -e "${BLUE}📋 Management Commands:${NC}"
    echo "  Status: podman ps"
    echo "  Logs: podman logs ${CONTAINER_NAME}"
    echo "  Stop: podman stop ${CONTAINER_NAME}"
    echo "  Start: podman start ${CONTAINER_NAME}"
    echo "  Restart: podman restart ${CONTAINER_NAME}"
    echo ""
    echo -e "${BLUE}🔧 Systemd Service:${NC}"
    echo "  Status: systemctl --user status strike-monitor"
    echo "  Stop: systemctl --user stop strike-monitor"
    echo "  Start: systemctl --user start strike-monitor"
    echo ""
    echo -e "${YELLOW}⚠️  Next Steps:${NC}"
    echo "  1. Copy your config into the container:"
    echo "     podman cp config.json ${CONTAINER_NAME}:/app/config.json"
    echo "  2. Or edit config inside container:"
    echo "     podman exec -it ${CONTAINER_NAME} nano /app/config.json"
    echo "  3. Restart: podman restart ${CONTAINER_NAME}"
    echo "  4. Access dashboard: http://${server_ip}:${PORT}"
}

# Main execution
main() {
    echo -e "${GREEN}"
    echo "╔════════════════════════════════════════════════╗"
    echo "║     Strike Finance Monitor - Simple Deploy     ║"
    echo "║                                                ║"
    echo "║  • Single HTTP check for liquidity status      ║"
    echo "║  • Multi-channel alerts (Email/Discord/Push)   ║"
    echo "║  • Web dashboard for monitoring                ║"
    echo "║  • Rootless container deployment               ║"
    echo "╚════════════════════════════════════════════════╝"
    echo -e "${NC}"
    
    check_podman
    setup_firewall
    create_config
    deploy_container
    setup_systemd_user
    show_status
    show_completion
}

main "$@"
