<?php
declare(strict_types=1);

// Additive integration for the existing portal. No schema migrations or credentials.
function fm_config(): array {
    $path = __DIR__ . '/../data/floodman-suite/config.php';
    if (!is_file($path)) throw new RuntimeException('Portal connection is not configured');
    $config = require $path;
    if (!is_array($config) || strlen((string)($config['secret'] ?? '')) < 32) {
        throw new RuntimeException('Portal connection is not configured');
    }
    return $config;
}

function fm_db(): PDO {
    $config = require __DIR__ . '/config.php';
    $path = (string)$config['DB_FILE'];
    if (!is_file($path)) throw new RuntimeException('Existing portal database is unavailable');
    $db = new PDO('sqlite:' . $path, null, null, [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC]);
    $db->exec('PRAGMA busy_timeout=5000');
    return $db;
}

function fm_text(array $input, string $field, int $limit, bool $required = false): string {
    if (isset($input[$field]) && !is_string($input[$field])) throw new InvalidArgumentException('Invalid ' . $field);
    $value = trim((string)($input[$field] ?? ''));
    if (strlen($value) > $limit || ($required && $value === '')) throw new InvalidArgumentException('Invalid ' . $field);
    return $value;
}

function fm_key(array $input): string {
    return hash('sha256', json_encode([fm_text($input, 'organization_id', 100, true),
        fm_text($input, 'workspace_id', 100, true), fm_text($input, 'job_id', 100, true)], JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR));
}

function fm_job(PDO $db, string $key): array {
    if (!preg_match('/^[a-f0-9]{64}$/D', $key)) throw new InvalidArgumentException('Invalid job reference');
    $query = $db->prepare('SELECT id,job_name,address FROM jobs WHERE client_job_id=?');
    $query->execute(['FLOODMAN:' . $key]);
    $job = $query->fetch();
    if (!$job) throw new OutOfBoundsException('Linked job not found');
    return $job;
}

function fm_verify_request(string $body, array $config, array $server): bool {
    $timestamp = (string)($server['HTTP_X_FLOODMAN_TIMESTAMP'] ?? '');
    $signature = (string)($server['HTTP_X_FLOODMAN_SIGNATURE'] ?? '');
    return ctype_digit($timestamp) && abs(time() - (int)$timestamp) <= 300
        && hash_equals(hash_hmac('sha256', $timestamp . '.' . $body, $config['secret']), $signature);
}

function fm_public_signature(string $purpose, string $key, string $asset, int $expires, array $config): string {
    return hash_hmac('sha256', implode(':', [$purpose, $key, $asset, $expires]), $config['secret']);
}

function fm_verify_view(array $query, array $config): bool {
    $expires = (string)($query['expires'] ?? '');
    if (!ctype_digit($expires) || (int)$expires < time() || (int)$expires > time() + 7200) return false;
    $purpose = (string)($query['view'] ?? '');
    if (!in_array($purpose, ['gallery', 'photo', 'layout', 'staff-gallery', 'staff-photo', 'staff-receipt', 'staff-video'], true)) return false;
    return hash_equals(fm_public_signature($purpose, (string)($query['key'] ?? ''),
        (string)($query['asset'] ?? ''), (int)$expires, $config), (string)($query['signature'] ?? ''));
}

function fm_asset_url(string $view, string $key, string $asset, int $expires, array $config): string {
    return 'floodman.php?' . http_build_query(['view' => $view, 'key' => $key, 'asset' => $asset,
        'expires' => $expires, 'signature' => fm_public_signature($view, $key, $asset, $expires, $config)]);
}

function fm_storage(): string {
    $path = realpath(__DIR__ . '/../data/floodman-suite');
    if ($path === false) throw new RuntimeException('Private portal storage is unavailable');
    return $path;
}

function fm_atomic_json(string $path, array $value): void {
    $temporary = $path . '.' . bin2hex(random_bytes(8)) . '.tmp';
    if (file_put_contents($temporary, json_encode($value, JSON_THROW_ON_ERROR), LOCK_EX) === false
        || !rename($temporary, $path)) throw new RuntimeException('Unable to save portal link');
    chmod($path, 0600);
}

function fm_upsert(PDO $db, array $input): array {
    $key = fm_key($input);
    $name = fm_text($input, 'customer_name', 200, true);
    $address = fm_text($input, 'address', 1000, true);
    $summary = fm_text($input, 'summary', 5000);
    $customer = fm_text($input, 'customer_id', 100, true);
    $property = fm_text($input, 'property_id', 100, true);
    $lock = fopen(fm_storage() . '/sync.lock', 'c');
    if (!$lock || !flock($lock, LOCK_EX)) throw new RuntimeException('Portal is busy');
    try {
        $db->beginTransaction();
        $query = $db->prepare('SELECT id FROM jobs WHERE client_job_id=?');
        $query->execute(['FLOODMAN:' . $key]);
        $id = $query->fetchColumn();
        $created = !$id;
        if ($created) {
            $insert = $db->prepare('INSERT INTO jobs(job_name,address,notes,employee_id,client_job_id) VALUES(?,?,?,NULL,?)');
            $insert->execute([$name, $address, $summary, 'FLOODMAN:' . $key]);
            $id = $db->lastInsertId();
        }
        $db->commit();
        // Recoverable metadata write: a retry finds the same unique job and repairs this file.
        fm_atomic_json(fm_storage() . '/' . $key . '.json', [
            'schema_version' => 1, 'portal_job_id' => (int)$id, 'customer_id' => $customer,
            'property_id' => $property, 'organization_id' => $input['organization_id'],
            'workspace_id' => $input['workspace_id'], 'job_id' => $input['job_id'],
            'roomflow_job_id' => fm_text($input, 'roomflow_job_id', 100),
            'estimate_id' => fm_text($input, 'estimate_id', 100), 'updated_at' => gmdate('c'),
        ]);
        return ['portal_job_id' => (int)$id, 'source_key' => $key, 'created' => $created,
            'portal_path' => '/portal/job.php?id=' . (int)$id];
    } catch (Throwable $exception) {
        if ($db->inTransaction()) $db->rollBack();
        throw $exception;
    } finally {
        flock($lock, LOCK_UN);
        fclose($lock);
    }
}

function fm_save_layout(PDO $db, array $input): array {
    $key = fm_key($input);
    fm_job($db, $key);
    $encoded = fm_text($input, 'image_base64', 17 * 1024 * 1024, true);
    $bytes = base64_decode($encoded, true);
    if ($bytes === false || strlen($bytes) > 12 * 1024 * 1024) throw new InvalidArgumentException('Invalid floor plan image');
    $info = @getimagesizefromstring($bytes);
    if (!$info || !in_array($info['mime'], ['image/jpeg', 'image/png'], true) || $info[0] * $info[1] > 40000000) {
        throw new InvalidArgumentException('Floor plan must be a JPEG or PNG image');
    }
    $digest = hash('sha256', $bytes);
    if (!hash_equals($digest, fm_text($input, 'sha256', 64, true))) throw new InvalidArgumentException('Floor plan checksum mismatch');
    $extension = $info['mime'] === 'image/jpeg' ? 'jpg' : 'png';
    $filename = $key . '-layout-' . $digest . '.' . $extension;
    $path = fm_storage() . '/' . $filename;
    if (!is_file($path)) {
        $temporary = $path . '.' . bin2hex(random_bytes(8)) . '.tmp';
        if (file_put_contents($temporary, $bytes, LOCK_EX) === false || !rename($temporary, $path)) throw new RuntimeException('Floor plan could not be saved');
        chmod($path, 0600);
    }
    fm_atomic_json(fm_storage() . '/' . $key . '-layout.json', ['filename' => $filename, 'mime' => $info['mime'], 'sha256' => $digest]);
    return ['source_key' => $key, 'sha256' => $digest];
}

function fm_serve_file(string $path, string $type): void {
    if (!is_file($path)) throw new OutOfBoundsException('Image is unavailable');
    header('Content-Type: ' . $type);
    header('Content-Length: ' . filesize($path));
    header('Content-Disposition: inline');
    readfile($path);
}

function fm_render_view(PDO $db, array $query, array $config): void {
    $key = (string)$query['key'];
    $view = (string)$query['view'];
    $staff = in_array($view, ['staff-gallery', 'staff-photo'], true);
    if ($staff) {
        if (!ctype_digit($key) || (int)$key < 1) throw new InvalidArgumentException('Invalid job');
        $statement = $db->prepare('SELECT id,job_name,address,client_job_id FROM jobs WHERE id=?');
        $statement->execute([(int)$key]);
        $job = $statement->fetch();
        if (!$job) throw new OutOfBoundsException('Job unavailable');
    } else $job = fm_job($db, $key);
    $expires = (int)$query['expires'];
    $layoutKey = $staff ? (str_starts_with((string)$job['client_job_id'], 'FLOODMAN:') ? substr($job['client_job_id'], 9) : '') : $key;
    $layoutPath = fm_storage() . '/' . $layoutKey . '-layout.json';
    if ($view === 'layout') {
        if (!is_file($layoutPath)) throw new OutOfBoundsException('Floor plan is unavailable');
        $layout = json_decode((string)file_get_contents($layoutPath), true, 16, JSON_THROW_ON_ERROR);
        fm_serve_file(fm_storage() . '/' . basename($layout['filename']), $layout['mime']);
        return;
    }
    if ($view === 'photo' || $view === 'staff-photo') {
        $photoId = (string)($query['asset'] ?? '');
        if (!ctype_digit($photoId)) throw new InvalidArgumentException('Invalid image reference');
        $statement = $db->prepare("SELECT filename FROM photos WHERE id=? AND job_id=? AND (media_type='photo' OR media_type IS NULL)");
        $statement->execute([(int)$photoId, (int)$job['id']]);
        $photo = $statement->fetch();
        if (!$photo) throw new OutOfBoundsException('Image is unavailable');
        $portalConfig = require __DIR__ . '/config.php';
        $root = realpath(rtrim($portalConfig['JOBS_PHOTOS_DIR'], '/') . '/' . (int)$job['id']);
        $path = $root ? realpath($root . '/' . basename($photo['filename'])) : false;
        if (!$root || !$path || dirname($path) !== $root) throw new OutOfBoundsException('Image is unavailable');
        $info = @getimagesize($path);
        if (!$info || !in_array($info['mime'], ['image/jpeg','image/png','image/webp','image/gif'], true)) throw new OutOfBoundsException('Image is unavailable');
        fm_serve_file($path, $info['mime']);
        return;
    }
    $statement = $db->prepare("SELECT id,caption,uploaded_at FROM photos WHERE job_id=? AND (media_type='photo' OR media_type IS NULL) ORDER BY uploaded_at,id");
    $statement->execute([(int)$job['id']]);
    $photos = $statement->fetchAll();
    $esc = static fn($value) => htmlspecialchars((string)$value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
    header('Content-Type: text/html; charset=utf-8');
    header("Content-Security-Policy: default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors https://floodman.oninetwork.com");
    echo '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Floodman project images</title><style>body{margin:0;padding:16px;font:16px system-ui;color:#12344b;background:#fff}h2{font-size:21px;margin:0 0 16px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(220px,100%),1fr));gap:16px}figure{margin:0;border:1px solid #d6e0e6;border-radius:12px;overflow:hidden}img{display:block;max-width:100%;height:auto}figcaption{padding:12px;overflow-wrap:anywhere}.plan{max-width:900px;margin:0 auto 24px}p{color:#526b7b}</style><body>';
    if ($staff) echo '<style>body{color:#edf4ff;background:#07111f}figure{background:#101d2f;border-color:#29415f}p{color:#9fb0c6}a:focus-visible{outline:2px solid #32a7ff;outline-offset:3px}h2{font-size:18px}</style>';
    if (is_file($layoutPath)) {
        $url = $esc(fm_asset_url('layout', $layoutKey, '', $expires, $config));
        echo '<h2>Floor plan</h2><figure class="plan"><a target="_blank" rel="noopener" href="' . $url . '"><img src="' . $url . '" alt="Saved RoomFlow floor plan"></a><figcaption>Captured RoomFlow floor plan</figcaption></figure>';
    } else echo '<h2>Floor plan</h2><p>A floor plan has not been added yet.</p>';
    echo '<h2>Project photos</h2><div class="grid">';
    foreach ($photos as $photo) {
        $url = $esc(fm_asset_url($staff ? 'staff-photo' : 'photo', $key, (string)$photo['id'], $expires, $config));
        echo '<figure><a target="_blank" rel="noopener" href="' . $url . '"><img loading="lazy" src="' . $url . '" alt="Project photo"></a><figcaption>' . $esc($photo['caption'] ?: 'Project photo') . '</figcaption></figure>';
    }
    echo '</div>';
    if (!$photos) echo '<p>No project photos have been added yet.</p>';
    echo '</body></html>';
}
