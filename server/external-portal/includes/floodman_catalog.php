<?php
declare(strict_types=1);

function fm_catalog_visible(array $job, array $input): bool {
    $source = (string)($job['client_job_id'] ?? '');
    if (!str_starts_with($source, 'FLOODMAN:')) return ($input['include_legacy'] ?? false) === true;
    $key = substr($source, 9);
    if (!preg_match('/^[a-f0-9]{64}$/D', $key)) return false;
    $path = fm_storage() . '/' . $key . '.json';
    if (!is_file($path)) return false;
    $record = json_decode((string)file_get_contents($path), true, 16, JSON_THROW_ON_ERROR);
    return ($record['workspace_id'] ?? '') === fm_text($input, 'workspace_id', 100, true)
        && ($record['organization_id'] ?? '') === fm_text($input, 'organization_id', 100, true);
}

function fm_catalog_job(PDO $db, array $input): array {
    $id = fm_text($input, 'portal_job_id', 20, true);
    if (!ctype_digit($id) || (int)$id < 1) throw new InvalidArgumentException('Invalid job');
    $statement = $db->prepare('SELECT id,job_name,address,client_job_id FROM jobs WHERE id=?');
    $statement->execute([(int)$id]);
    $job = $statement->fetch();
    if (!$job || !fm_catalog_visible($job, $input)) throw new OutOfBoundsException('Job unavailable');
    return $job;
}

function fm_catalog(PDO $db, array $input): array {
    fm_text($input, 'workspace_id', 100, true);
    fm_text($input, 'organization_id', 100, true);
    $before = fm_text($input, 'before_id', 20);
    $search = fm_text($input, 'search', 200);
    if ($before !== '' && !ctype_digit($before)) throw new InvalidArgumentException('Invalid page');
    $statement = $db->prepare('SELECT id,job_name,address,client_job_id FROM jobs WHERE id<? AND (job_name LIKE ? OR address LIKE ?) ORDER BY id DESC LIMIT 200');
    $statement->execute([$before === '' ? PHP_INT_MAX : (int)$before, '%' . $search . '%', '%' . $search . '%']);
    $items = []; $last = null; $scanned = 0;
    foreach ($statement as $job) {
        $last = (int)$job['id']; $scanned++;
        if (!fm_catalog_visible($job, $input)) continue;
        $items[] = ['id' => (int)$job['id'], 'name' => $job['job_name'], 'address' => $job['address'],
            'legacy' => !str_starts_with((string)$job['client_job_id'], 'FLOODMAN:')];
        if (count($items) >= 50) break;
    }
    return ['items' => $items, 'next_before_id' => count($items) >= 50 || $scanned >= 200 ? $last : null];
}

function fm_catalog_upload(PDO $db, array $input): array {
    $job = fm_catalog_job($db, $input);
    $operation = fm_text($input, 'operation_id', 80, true);
    if (!preg_match('/^[a-f0-9-]{36}$/D', $operation)) throw new InvalidArgumentException('Invalid upload reference');
    $caption = fm_text($input, 'caption', 1000);
    $bytes = base64_decode(fm_text($input, 'image_base64', 17 * 1024 * 1024, true), true);
    if ($bytes === false || strlen($bytes) > 12 * 1024 * 1024) throw new InvalidArgumentException('Image too large');
    $info = @getimagesizefromstring($bytes);
    $extensions = ['image/jpeg'=>'jpg', 'image/png'=>'png', 'image/webp'=>'webp', 'image/gif'=>'gif'];
    if (!$info || !isset($extensions[$info['mime']]) || $info[0] * $info[1] > 40000000) throw new InvalidArgumentException('Invalid image');
    $digest = hash('sha256', $bytes);
    if (!hash_equals($digest, fm_text($input, 'sha256', 64, true))) throw new InvalidArgumentException('Image checksum mismatch');
    $filename = 'erp-' . $operation . '-' . $digest . '.' . $extensions[$info['mime']];
    $clientId = 'ERP:' . $operation;
    $lock = fopen(fm_storage() . '/upload.lock', 'c');
    if (!$lock || !flock($lock, LOCK_EX)) throw new RuntimeException('Portal busy');
    try {
        $find = $db->prepare('SELECT id,filename FROM photos WHERE job_id=? AND client_photo_id=?');
        $find->execute([(int)$job['id'], $clientId]);
        $existing = $find->fetch();
        if ($existing) {
            if ($existing['filename'] !== $filename) throw new InvalidArgumentException('Upload reference conflict');
            $config = require __DIR__ . '/config.php';
            $original = rtrim($config['JOBS_PHOTOS_DIR'], '/') . '/' . (int)$job['id'] . '/' . $filename;
            if (!is_file($original) || hash_file('sha256', $original) !== $digest) throw new RuntimeException('Hosted original requires recovery');
            return ['photo_id'=>(int)$existing['id'], 'sha256'=>$digest, 'replayed'=>true];
        }
        $config = require __DIR__ . '/config.php';
        $directory = rtrim($config['JOBS_PHOTOS_DIR'], '/') . '/' . (int)$job['id'];
        if (!is_dir($directory) && !mkdir($directory, 0755, true)) throw new RuntimeException('Storage unavailable');
        $path = $directory . '/' . $filename;
        if (is_file($path) && hash_file('sha256', $path) !== $digest) throw new RuntimeException('Storage conflict');
        if (!is_file($path)) {
            $temporary = $directory . '/.ht-upload-' . bin2hex(random_bytes(10));
            if (file_put_contents($temporary, $bytes, LOCK_EX) === false || !rename($temporary, $path)) throw new RuntimeException('Upload unavailable');
        }
        $insert = $db->prepare("INSERT INTO photos(job_id,filename,caption,media_type,client_photo_id,client_job_id) VALUES(?,?,?,'photo',?,?)");
        $insert->execute([(int)$job['id'], $filename, $caption, $clientId, $job['client_job_id'] ?: null]);
        return ['photo_id'=>(int)$db->lastInsertId(), 'sha256'=>$digest, 'replayed'=>false];
    } finally { flock($lock, LOCK_UN); fclose($lock); }
}
