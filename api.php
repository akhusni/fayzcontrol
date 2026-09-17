<?php
// Fayz Medical House — Ultra-Fast API Proxy & Daemon Watchdog
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type, Authorization');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    http_response_code(200);
    exit;
}

$port = 3000;
$server_script = __DIR__ . '/server.py';

// Function to check if server.py is responding on port
function is_server_alive($port) {
    $fp = @fsockopen('127.0.0.1', $port, $errno, $errstr, 0.2);
    if ($fp) {
        fclose($fp);
        return true;
    }
    return false;
}

// Ensure server.py is running (or restart if requested)
if (!is_server_alive($port) || isset($_GET['restart_backend'])) {
    if (isset($_GET['restart_backend'])) {
        shell_exec('pkill -f "python3.*server.py" 2>/dev/null; pkill -f "python.*server.py" 2>/dev/null');
        usleep(300000);
    }
    $cmd = 'cd ' . escapeshellarg(__DIR__) . ' && nohup python3 server.py 3000 > server_log.txt 2>&1 &';
    shell_exec($cmd);
    for ($i = 0; $i < 20; $i++) {
        usleep(200000); // 200ms
        if (is_server_alive($port)) break;
    }
    if (isset($_GET['restart_backend'])) {
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode([
            'success' => true,
            'restarted' => true,
            'alive' => is_server_alive($port),
            'log' => file_exists(__DIR__ . '/server_log.txt') ? substr(file_get_contents(__DIR__ . '/server_log.txt'), -1000) : ''
        ]);
        exit;
    }
}

// Build target URL
$uri = $_SERVER['REQUEST_URI'];
$target_url = 'http://127.0.0.1:' . $port . $uri;

// Forward via cURL
$ch = curl_init($target_url);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_CUSTOMREQUEST, $_SERVER['REQUEST_METHOD']);
curl_setopt($ch, CURLOPT_TIMEOUT, 30);

// Forward request body
$input = file_get_contents('php://input');
if (!empty($input)) {
    curl_setopt($ch, CURLOPT_POSTFIELDS, $input);
}

// Forward Content-Type header
$headers = [];
if (!empty($_SERVER['CONTENT_TYPE'])) {
    $headers[] = 'Content-Type: ' . $_SERVER['CONTENT_TYPE'];
} else {
    $headers[] = 'Content-Type: application/json; charset=utf-8';
}
curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);

$response = curl_exec($ch);
$http_code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
$curl_error = curl_error($ch);
curl_close($ch);

if ($response === false) {
    http_response_code(502);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(['error' => 'API Backend starting up or unreachable', 'details' => $curl_error]);
    exit;
}

http_response_code($http_code);
header('Content-Type: application/json; charset=utf-8');
echo $response;
?>
