# HTTP CONNECT proxy for commands entered in docker-service shell.
export http_proxy=http://192.168.5.45:6152
export https_proxy=http://192.168.5.45:6152
export HTTP_PROXY="$http_proxy"
export HTTPS_PROXY="$https_proxy"
export no_proxy=localhost,127.0.0.1,::1,172.30.0.0/16,192.168.5.0/24
export NO_PROXY="$no_proxy"
