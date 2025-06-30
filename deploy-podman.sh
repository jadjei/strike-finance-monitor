#!/bin/bash

# Strike Finance Monitor - Podman Deployment Script
# Clean, rootless deployment avoiding SELinux issues

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
CONTAINER_NAME="strike-finance-monitor"
IMAGE_NAME="strike-monitor"
PORT="5000"
DEPLOYMENT_METHOD=""
SKIP_COMPOSE_PROMPT=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-compose)
            SKIP_COMPOSE_PROMPT=true
            shift
            ;;
        --help|-h)
            echo "Strike Finance Monitor - Podman Deployment"
            echo ""
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --skip-compose    Skip podman-compose installation prompt"
            echo "  --help, -h        Show this help message"
            echo ""
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

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
            log_error "No config.json or config.json.template found"
            exit 1
        fi
    else
        log_success "Using existing config.json"
    fi
}

check_podman_compose() {
    log_info "Checking podman-compose availability..."
    
    if ! command -v podman-compose &> /dev/null; then
        if [[ "$SKIP_COMPOSE_PROMPT" == "true" ]]; then
            log_info "Skipping podman-compose installation (--skip-compose flag)"
            return 1
        fi
        
        echo ""
        echo -e "${YELLOW}podman-compose is not installed.${NC}"
        echo ""
        echo "podman-compose provides:"
        echo "  • Declarative container management"
        echo "  • Easy multi-container orchestration"
        echo "  • Simplified restart/rebuild workflows"
        echo ""
        echo "Without it, we'll use direct podman commands (still works great!)."
        echo ""
        
        read -p "Would you like to install podman-compose? (y/N) " -n 1 -r
        echo
        
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            log_info "Installing podman-compose..."
            
            if install_podman_compose; then
                log_success "podman-compose installed successfully"
                return 0
            else
                log_warning "podman-compose installation failed, continuing with direct podman"
                return 1
            fi
        else
            log_info "Skipping podman-compose installation"
            return 1
        fi
    else
        log_success "podman-compose is already available"
        return 0
    fi
}

install_podman_compose() {
    # Try package manager first
    if command -v dnf &> /dev/null; then
        if sudo dnf install -y podman-compose 2>/dev/null; then
            return 0
        fi
    elif command -v apt &> /dev/null; then
        if sudo apt install -y podman-compose 2>/dev/null; then
            return 0
        fi
    fi
    
    # Fallback to pip installation
    log_info "Package not available via system package manager, trying pip..."
    
    # Check if pip is available
    if ! command -v pip3 &> /dev/null; then
        log_error "pip3 is not available and package manager doesn't have podman-compose"
        echo "You can install it manually later with: pip3 install --user podman-compose"
        return 1
    fi
    
    # Install via pip
    if pip3 install --user podman-compose; then
        # Add to PATH for current session
        export PATH="$HOME/.local/bin:$PATH"
        
        # Check if it's now available
        if command -v podman-compose &> /dev/null; then
            log_info "Added $HOME/.local/bin to PATH for this session"
            echo ""
            echo -e "${YELLOW}Note:${NC} Add this to your ~/.bashrc for permanent PATH:"
            echo "export PATH=\"\$HOME/.local/bin:\$PATH\""
            return 0
        else
            log_error "podman-compose installed but not found in PATH"
            return 1
        fi
    else
        log_error "pip installation failed"
        return 1
    fi
}

deploy_application() {
    log_info "Deploying Strike Finance Monitor..."
    
    # Try podman-compose first, fallback to direct podman
    if check_podman_compose; then
        if deploy_with_compose; then
            DEPLOYMENT_METHOD="podman-compose"
            return 0
        else
            log_warning "podman-compose deployment failed, trying direct podman..."
        fi
    fi
    
    # Fallback to direct podman commands
    deploy_with_podman
    DEPLOYMENT_METHOD="podman"
}

deploy_with_compose() {
    log_info "Deploying with podman-compose..."
    
    # Stop any existing containers
    podman-compose down 2>/dev/null || true
    
    # Deploy using compose
    podman-compose up -d --build
    
    # Wait for container to be ready
    log_info "Waiting for container to start..."
    sleep 5
    
    # Check if container is running
    if podman-compose ps | grep -q "Up"; then
        log_success "Container deployed successfully with podman-compose"
        return 0
    else
        log_error "Container deployment failed"
        return 1
    fi
}

deploy_with_podman() {
    log_info "Deploying with direct podman commands..."
    
    # Build image
    log_info "Building container image..."
    podman build -t ${IMAGE_NAME} .
    
    # Stop and remove existing container
    podman stop ${CONTAINER_NAME} 2>/dev/null || true
    podman rm ${CONTAINER_NAME} 2>/dev/null || true
    
    # Create volumes for persistence
    podman volume create strike-logs 2>/dev/null || true
    podman volume create strike-db 2>/dev/null || true
    
    # Run container
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
    
    log_success "Container deployed successfully with podman"
}

setup_systemd_user() {
    log_info "Setting up systemd user service..."
    
    # Create user systemd directory
    mkdir -p ~/.config/systemd/user
    
    # Generate systemd service based on deployment method
    if [[ "${DEPLOYMENT_METHOD}" == "podman-compose" ]]; then
        cat > ~/.config/systemd/user/strike-monitor.service << EOF
[Unit]
Description=Strike Finance Monitor Container (Compose)
After=network.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$(pwd)
ExecStart=/usr/bin/podman-compose up -d
ExecStop=/usr/bin/podman-compose down
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
EOF
    else
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
    fi

    # Enable and start service
    systemctl --user daemon-reload
    systemctl --user enable strike-monitor.service
    systemctl --user start strike-monitor.service
    
    # Enable lingering for user services
    sudo loginctl enable-linger $(whoami)
    
    log_success "Systemd user service configured for ${DEPLOYMENT_METHOD}"
}

show_status() {
    log_info "Checking deployment status..."
    
    if [[ "${DEPLOYMENT_METHOD}" == "podman-compose" ]]; then
        if podman-compose ps | grep -q "Up"; then
            log_success "Container is running (via podman-compose)"
            podman-compose ps
        else
            log_error "Container is not running"
        fi
        
        echo ""
        log_info "Recent logs:"
        podman-compose logs --tail 10
        
    else
        if podman ps --format "table {{.Names}} {{.Status}} {{.Ports}}" | grep -q ${CONTAINER_NAME}; then
            log_success "Container is running (via podman)"
            podman ps --filter name=${CONTAINER_NAME}
        else
            log_error "Container is not running"
        fi
        
        echo ""
        log_info "Recent logs:"
        podman logs --tail 10 ${CONTAINER_NAME}
    fi
}

show_completion() {
    local server_ip
    server_ip=$(hostname -I | awk '{print $1}' || echo "localhost")
    
    echo ""
    log_success "Strike Finance Monitor deployed with Podman (${DEPLOYMENT_METHOD})!"
    echo ""
    echo -e "${BLUE}🐋 Container Info:${NC}"
    echo "  Method: ${DEPLOYMENT_METHOD}"
    echo "  Name: ${CONTAINER_NAME}"
    if [[ "${DEPLOYMENT_METHOD}" != "podman-compose" ]]; then
        echo "  Image: ${IMAGE_NAME}"
    fi
    echo "  Dashboard: http://${server_ip}:${PORT}"
    echo ""
    
    if [[ "${DEPLOYMENT_METHOD}" == "podman-compose" ]]; then
        echo -e "${BLUE}📋 Management Commands (Compose):${NC}"
        echo "  Status: podman-compose ps"
        echo "  Logs: podman-compose logs"
        echo "  Stop: podman-compose down"
        echo "  Start: podman-compose up -d"
        echo "  Restart: podman-compose restart"
        echo "  Rebuild: podman-compose up -d --build"
    else
        echo -e "${BLUE}📋 Management Commands (Podman):${NC}"
        echo "  Status: podman ps"
        echo "  Logs: podman logs ${CONTAINER_NAME}"
        echo "  Stop: podman stop ${CONTAINER_NAME}"
        echo "  Start: podman start ${CONTAINER_NAME}"
        echo "  Restart: podman restart ${CONTAINER_NAME}"
        echo "  Remove: podman rm ${CONTAINER_NAME}"
    fi
    
    echo ""
    echo -e "${BLUE}🔧 Systemd Service:${NC}"
    echo "  Status: systemctl --user status strike-monitor"
    echo "  Stop: systemctl --user stop strike-monitor"
    echo "  Start: systemctl --user start strike-monitor"
    echo ""
    echo -e "${YELLOW}⚠️  Important:${NC}"
    echo "  1. Edit config.json with your credentials"
    if [[ "${DEPLOYMENT_METHOD}" == "podman-compose" ]]; then
        echo "  2. Restart: podman-compose restart"
    else
        echo "  2. Restart: podman restart ${CONTAINER_NAME}"
    fi
    echo "  3. Access dashboard: http://${server_ip}:${PORT}"
}

# Main execution
main() {
    echo -e "${GREEN}"
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║           Strike Finance Monitor - Podman Deployment           ║"
    echo "║                                                                ║"
    echo "║  Intelligent hybrid deployment:                                ║"
    echo "║  • Tries podman-compose first (with user prompt)               ║"
    echo "║  • Falls back to direct podman commands                        ║"
    echo "║  • Handles all system setup automatically                      ║"
    echo "║                                                                ║"
    echo "║  Benefits: No SELinux issues, rootless, auto-restart           ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
    
    check_podman
    setup_firewall
    create_config
    deploy_application
    setup_systemd_user
    show_status
    show_completion
}

main "$@"
