<?php
/**
 * Fayz Medical House — Gateway Proxy & Watchdog
 *
 * Forwards requests to the Python backend (server.py) on 127.0.0.1:3000.
 * Ensures server.py is running via PM2 / background daemon.
 * Forwards cookies, headers, and request body transparently.
 */

$port = 3000;

function is_server_alive($port) {
    $fp = @fsockopen('127.0.0.1', $port, $errno, $errstr, 0.3);
    if ($fp) {
        fclose($fp);
        return true;
    }
    return false;
}

// Watchdog: auto-start server.py if down
if (!is_server_alive($port)) {
    putenv('PATH=/var/www/s0377/data/node/bin:/var/www/s0377/data/.local/bin:/usr/local/bin:/usr/bin:/bin');
    putenv('HOME=/var/www/s0377/data');
    putenv('PM2_HOME=/var/www/s0377/data/.pm2');

    $pm2 = '/var/www/s0377/data/node/bin/pm2';
    $dir = __DIR__;
    if (file_exists($pm2)) {
        shell_exec("cd " . escapeshellarg($dir) . " && $pm2 start server.py --name fayzcontrol --interpreter python3 -- 3000 > /dev/null 2>&1 &");
    } else {
        shell_exec("cd " . escapeshellarg($dir) . " && nohup python3 server.py 3000 > server.log 2>&1 &");
    }

    for ($i = 0; $i < 20; $i++) {
        usleep(150000);
        if (is_server_alive($port)) break;
    }
}

// Fallback headers helper
if (!function_exists('getallheaders')) {
    function getallheaders() {
        $headers = [];
        foreach ($_SERVER as $name => $value) {
            if (substr($name, 0, 5) == 'HTTP_') {
                $header_name = str_replace(' ', '-', ucwords(strtolower(str_replace('_', ' ', substr($name, 5)))));
                $headers[$header_name] = $value;
            } elseif (in_array(strtolower($name), ['content_type', 'content_length'])) {
                $header_name = str_replace(' ', '-', ucwords(strtolower(str_replace('_', ' ', $name))));
                $headers[$header_name] = $value;
            }
        }
        return $headers;
    }
}

$uri = $_SERVER['REQUEST_URI'];
$target_url = 'http://127.0.0.1:' . $port . $uri;

$ch = curl_init($target_url);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_HEADER, true);
curl_setopt($ch, CURLOPT_CUSTOMREQUEST, $_SERVER['REQUEST_METHOD']);
curl_setopt($ch, CURLOPT_TIMEOUT, 60);

// Determine client IP
$client_ip = !empty($_SERVER['HTTP_X_REAL_IP']) ? $_SERVER['HTTP_X_REAL_IP'] :
             (!empty($_SERVER['HTTP_X_FORWARDED_FOR']) ? explode(',', $_SERVER['HTTP_X_FORWARDED_FOR'])[0] : $_SERVER['REMOTE_ADDR']);

$forward_headers = [
    'X-Real-IP: ' . trim($client_ip),
    'X-Forwarded-For: ' . trim($client_ip),
    'X-Forwarded-Proto: https'
];

foreach (getallheaders() as $name => $value) {
    $lower = strtolower($name);
    if (in_array($lower, ['host', 'content-length', 'connection'])) continue;
    $forward_headers[] = "$name: $value";
}
curl_setopt($ch, CURLOPT_HTTPHEADER, $forward_headers);

// Body
$input = file_get_contents('php://input');
if (!empty($input) || in_array($_SERVER['REQUEST_METHOD'], ['POST', 'PUT', 'PATCH'])) {
    curl_setopt($ch, CURLOPT_POSTFIELDS, $input);
}

$response = curl_exec($ch);
$http_code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
$header_size = curl_getinfo($ch, CURLINFO_HEADER_SIZE);
$curl_error = curl_error($ch);
curl_close($ch);

if ($response === false) {
    http_response_code(502);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode([
        'error' => 'Backend starting up or unreachable',
        'details' => $curl_error
    ]);
    exit;
}

$res_headers = substr($response, 0, $header_size);
$res_body = substr($response, $header_size);

http_response_code($http_code);

foreach (explode("\r\n", $res_headers) as $h) {
    if (empty($h) || stripos($h, 'Transfer-Encoding:') === 0 || stripos($h, 'Connection:') === 0) continue;
    if (stripos($h, 'Set-Cookie:') === 0) {
        header($h, false);
    } else {
        header($h, true);
    }
}

echo $res_body;
