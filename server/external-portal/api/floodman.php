<?php
declare(strict_types=1);
require_once __DIR__ . '/../includes/floodman_bridge.php';
require_once __DIR__ . '/../includes/floodman_catalog.php';
require_once __DIR__ . '/../includes/floodman_job_tools.php';
header('Cache-Control: no-store, private');
header('Referrer-Policy: no-referrer');
header('X-Content-Type-Options: nosniff');
header('X-Robots-Tag: noindex, nofollow, noarchive');
try {
    $config = fm_config();
    if ($_SERVER['REQUEST_METHOD'] === 'GET' && isset($_GET['view'])) {
        if (!fm_verify_view($_GET, $config)) { http_response_code(403); exit('This image link is invalid or expired. Reopen your estimate.'); }
        if (in_array($_GET['view'], ['staff-receipt','staff-video'], true)) fm_staff_media(fm_db(), $_GET);
        else fm_render_view(fm_db(), $_GET, $config);
        exit;
    }
    header('Content-Type: application/json');
    if ($_SERVER['REQUEST_METHOD'] !== 'POST') { http_response_code(405); exit('{"error":"POST required"}'); }
    if ((int)($_SERVER['CONTENT_LENGTH'] ?? 0) > 18 * 1024 * 1024) { http_response_code(413); exit('{"error":"Request too large"}'); }
    $body = (string)file_get_contents('php://input', false, null, 0, 18 * 1024 * 1024 + 1);
    if (strlen($body) > 18 * 1024 * 1024) { http_response_code(413); exit('{"error":"Request too large"}'); }
    if (!fm_verify_request($body, $config, $_SERVER)) { http_response_code(401); exit('{"error":"Authentication required"}'); }
    $input = json_decode($body, true, 32, JSON_THROW_ON_ERROR);
    if (!is_array($input)) throw new InvalidArgumentException('Invalid request');
    $action = fm_text($input, 'action', 40, true);
    $db = fm_db();
    if ($action === 'health') {
        $columns = $db->query('PRAGMA table_info(jobs)')->fetchAll(PDO::FETCH_COLUMN, 1);
        if (!in_array('client_job_id', $columns, true)) throw new RuntimeException('Portal stable job identifiers are unavailable');
        $result = ['status' => 'ready', 'schema_version' => 1, 'php_runtime' => PHP_MAJOR_VERSION . '.' . PHP_MINOR_VERSION, 'capabilities' => ['job-upsert', 'roomflow-layout', 'signed-gallery', 'staff-catalog', 'staff-upload', 'staff-job-tools', 'chunked-video']];
    } elseif ($action === 'upsert-job') $result = fm_upsert($db, $input);
    elseif ($action === 'save-layout') $result = fm_save_layout($db, $input);
    elseif ($action === 'list-jobs') $result = fm_catalog($db, $input);
    elseif ($action === 'get-job') $result = ['job' => fm_catalog_job($db, $input)];
    elseif ($action === 'upload-photo') $result = fm_catalog_upload($db, $input);
    elseif ($action === 'job-tools') $result = fm_job_tools($db, $input);
    elseif ($action === 'job-mutate') $result = fm_tool_mutate($db, $input);
    elseif ($action === 'video-chunk') $result = fm_video_chunk($db, $input);
    else throw new InvalidArgumentException('Unknown action');
    echo json_encode($result, JSON_THROW_ON_ERROR);
} catch (InvalidArgumentException | JsonException $exception) {
    http_response_code(422); echo '{"error":"Invalid portal request"}';
} catch (OutOfBoundsException $exception) {
    http_response_code(404); echo '{"error":"Portal job or image not found"}';
} catch (Throwable $exception) {
    http_response_code(503); echo '{"error":"Portal connection temporarily unavailable"}';
}
