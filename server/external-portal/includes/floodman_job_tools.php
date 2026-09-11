<?php
declare(strict_types=1);

// Staff tools for the existing schema. The private journal supplies stable operations
// without adding columns to the production portal database.
function fm_revision(array $row): string {
    ksort($row);
    return hash('sha256', json_encode($row, JSON_THROW_ON_ERROR));
}

function fm_tool_table(string $kind): string {
    return match ($kind) { 'note'=>'job_notes', 'receipt'=>'receipts', 'content'=>'contents',
        'photo', 'video'=>'photos', 'job'=>'jobs', default=>throw new InvalidArgumentException('Invalid tool') };
}

function fm_tool_rows(PDO $db, string $table, int $job): array {
    $query = $db->prepare("SELECT * FROM $table WHERE job_id=? ORDER BY id DESC LIMIT 501");
    $query->execute([$job]);
    return $query->fetchAll();
}

function fm_job_tools(PDO $db, array $input): array {
    $job = fm_catalog_job($db, $input); $result = ['job'=>$job, 'truncated'=>false];
    $fullJob=fm_row($db,'jobs',(int)$job['id']);
    $result['job']=array_merge($job,['notes'=>$fullJob['notes'] ?? '', 'default_topic'=>$fullJob['default_topic'] ?? '', 'revision'=>fm_revision($fullJob)]);
    foreach (['notes'=>'job_notes', 'receipts'=>'receipts', 'contents'=>'contents', 'media'=>'photos'] as $key=>$table) {
        $rows = fm_tool_rows($db, $table, (int)$job['id']);
        if (count($rows) > 500) { $result['truncated'] = true; array_pop($rows); }
        foreach ($rows as &$row) {
            $row['revision'] = fm_revision($row);
            $row['id'] = (int)$row['id'];
            $row['job_id'] = (int)$row['job_id'];
            unset($row['filename'], $row['client_photo_id'], $row['client_job_id']);
            if ($key === 'contents') {
                $query = $db->prepare('SELECT p.id FROM content_photos cp JOIN photos p ON p.id=cp.photo_id WHERE cp.content_id=? AND p.job_id=? ORDER BY p.id');
                $query->execute([$row['id'], $job['id']]);
                $row['photo_ids'] = array_map('intval',$query->fetchAll(PDO::FETCH_COLUMN));
            }
        }
        unset($row); $result[$key] = $rows;
    }
    $query = $db->prepare('SELECT COALESCE(SUM(amount),0) FROM receipts WHERE job_id=?');
    $query->execute([$job['id']]); $result['receipt_total'] = round((float)$query->fetchColumn(), 2);
    $config = require __DIR__ . '/config.php';
    foreach (['topics'=>'TOPICS','categories'=>'CONTENT_CATEGORIES','conditions'=>'CONTENT_CONDITIONS'] as $key=>$setting) {
        $result[$key] = array_values(array_filter($config[$setting] ?? [], 'is_string'));
    }
    return $result;
}

function fm_tool_fields(string $kind, array $fields): array {
    $spec = match ($kind) {
        'note'=>['note'=>10000], 'receipt'=>['vendor'=>200,'notes'=>5000],
        'content'=>['name'=>200,'description'=>5000,'category'=>200,'condition'=>200],
        'photo', 'video'=>['caption'=>1000,'topic'=>200],
        'job'=>['job_name'=>200,'address'=>1000,'notes'=>5000,'default_topic'=>200],
        default=>throw new InvalidArgumentException('Invalid tool')
    };
    $out = [];
    foreach ($spec as $name=>$limit) $out[$name] = fm_text($fields, $name, $limit, in_array($name,['note','name','job_name','address'],true));
    if ($kind === 'receipt') {
        $amount = fm_text($fields, 'amount', 20);
        if ($amount !== '' && (!preg_match('/^\d{1,8}(\.\d{1,2})?$/D', $amount))) throw new InvalidArgumentException('Invalid amount');
        $out['amount'] = $amount === '' ? null : (float)$amount;
    }
    return $out;
}

function fm_row(PDO $db, string $table, int $id): ?array {
    $query = $db->prepare("SELECT * FROM $table WHERE id=?"); $query->execute([$id]);
    return $query->fetch() ?: null;
}

function fm_change(PDO $db, string $table, ?array $before, array $fields): array {
    $id = $before ? (int)$before['id'] : (int)$db->query("SELECT COALESCE(MAX(id),0)+1 FROM $table")->fetchColumn();
    if (!$before && $db->query("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'")->fetchColumn()) {
        $sequence=$db->prepare('SELECT seq FROM sqlite_sequence WHERE name=?'); $sequence->execute([$table]);
        $id=max($id,(int)$sequence->fetchColumn()+1); // Never reuse a removed asset's signed-link ID.
    }
    // Populate defaults using the existing schema; no ALTER/CREATE on the portal DB.
    $after = $before;
    if (!$after) {
        $after = [];
        foreach ($db->query("PRAGMA table_info($table)") as $column) {
            $default = $column['dflt_value'];
            $after[$column['name']] = $default === 'CURRENT_TIMESTAMP' ? gmdate('Y-m-d H:i:s')
                : ($default === null ? null : trim((string)$default, "'\""));
        }
        $after['id'] = $id;
    }
    $after = array_replace($after, $fields);
    return ['table'=>$table,'id'=>$id,'before'=>$before,'after'=>$after];
}

function fm_apply_plan(PDO $db, array $changes): void {
    $before = true; $after = true;
    foreach ($changes as $change) {
        $current = fm_row($db, $change['table'], $change['id']);
        // SQLite may normalize numeric affinity; compare values, not PHP types.
        $before = $before && $current == $change['before'];
        $after = $after && $current == $change['after'];
    }
    if ($after) return; // Previous COMMIT succeeded, but its acknowledgement was lost.
    if (!$before) throw new InvalidArgumentException('Record changed; refresh before trying again');
    foreach ($changes as $change) {
        $table = $change['table'];
        if ($change['after'] === null) {
            $db->prepare("DELETE FROM $table WHERE id=?")->execute([$change['id']]);
        } elseif ($change['before'] === null) {
            $keys = array_keys($change['after']);
            $columns = implode(',', array_map(static fn($key)=>'"'.$key.'"', $keys));
            $marks = implode(',', array_fill(0,count($keys),'?'));
            $db->prepare("INSERT INTO $table($columns) VALUES($marks)")->execute(array_values($change['after']));
        } else {
            $values = $change['after']; unset($values['id']);
            $sets = implode(',', array_map(static fn($key)=>'"'.$key.'"=?',array_keys($values)));
            $db->prepare("UPDATE $table SET $sets WHERE id=?")->execute([...array_values($values),$change['id']]);
        }
    }
}

function fm_media_bytes(array $input, string $kind): array {
    $bytes = base64_decode(fm_text($input,'image_base64',17*1024*1024,true),true);
    if ($bytes === false || strlen($bytes)>12*1024*1024) throw new InvalidArgumentException('Invalid image');
    $info = @getimagesizefromstring($bytes);
    $extensions = ['image/jpeg'=>'jpg','image/png'=>'png','image/webp'=>'webp','image/gif'=>'gif'];
    if (!$info || !isset($extensions[$info['mime']]) || $info[0]*$info[1]>40000000) throw new InvalidArgumentException('Invalid image');
    $digest = hash('sha256',$bytes);
    if (!hash_equals($digest, fm_text($input,'sha256',64,true))) throw new InvalidArgumentException('Checksum mismatch');
    return [$bytes,$extensions[$info['mime']],$digest];
}

function fm_tool_mutate(PDO $db, array $input): array {
    $job = fm_catalog_job($db,$input);
    $operation = fm_text($input,'operation_id',36,true);
    if (!preg_match('/^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$/D',$operation)) throw new InvalidArgumentException('Invalid operation');
    $kind = fm_text($input,'kind',20,true); $table = fm_tool_table($kind);
    $mode = fm_text($input,'mode',20,true);
    if (!in_array($mode,['add','edit','remove'],true)) throw new InvalidArgumentException('Invalid operation');
    if ($kind==='job' && $mode!=='edit') throw new InvalidArgumentException('Use the ERP to create jobs');
    $fields = $mode === 'remove' ? [] : fm_tool_fields($kind,$input['fields'] ?? []);
    $fingerprint = $input; unset($fingerprint['image_base64']);
    $fingerprint = hash('sha256',json_encode($fingerprint,JSON_THROW_ON_ERROR));
    $journal = fm_storage().'/operation-'.$operation.'.json';
    $lock = fopen(fm_storage().'/tools.lock','c');
    if (!$lock || !flock($lock,LOCK_EX)) throw new RuntimeException('Portal busy');
    $transaction = false;
    try {
        $plan = is_file($journal) ? json_decode((string)file_get_contents($journal),true,32,JSON_THROW_ON_ERROR) : null;
        if ($plan && !hash_equals($plan['fingerprint'],$fingerprint)) throw new InvalidArgumentException('Operation reference conflict');
        if ($plan && $plan['status']==='DONE') {
            if ($kind==='video' && $mode==='add') fm_video_cleanup($input);
            return array_merge($plan['result'],['replayed'=>true]);
        }
        $db->exec('BEGIN IMMEDIATE'); $transaction = true;
        if (!$plan) {
            $changes = []; $before = null;
            if ($mode !== 'add') {
                $id = fm_text($input,'record_id',20,true);
                if (!ctype_digit($id)) throw new InvalidArgumentException('Invalid record');
                $before = fm_row($db,$table,(int)$id);
                if (!$before || (int)$before[$kind==='job' ? 'id' : 'job_id'] !== (int)$job['id']) throw new OutOfBoundsException('Record unavailable');
                if (in_array($kind,['photo','video'],true) && ($before['media_type'] ?: 'photo') !== $kind) throw new OutOfBoundsException('Record unavailable');
                if (!hash_equals(fm_revision($before),fm_text($input,'revision',64,true))) throw new InvalidArgumentException('Record changed');
            }
            if ($mode==='remove') {
                if (in_array($kind,['content','photo','video'],true)) {
                    $column = $kind==='content' ? 'content_id' : 'photo_id';
                    $links = $db->prepare("SELECT * FROM content_photos WHERE $column=?"); $links->execute([$before['id']]);
                    foreach ($links as $link) $changes[]=['table'=>'content_photos','id'=>(int)$link['id'],'before'=>$link,'after'=>null];
                }
                $change=['table'=>$table,'id'=>(int)$before['id'],'before'=>$before,'after'=>null];
            } else {
                if ($kind==='note') {
                    $fields['updated_at']=gmdate('Y-m-d H:i:s');
                    if (!$before) $fields['created_by']='ERP staff';
                }
                if ($mode==='add' && in_array($kind,['receipt','photo','video'],true)) {
                    if ($kind==='video') [$videoPath,$ext,$digest] = fm_video_commit($input);
                    else [$bytes,$ext,$digest] = fm_media_bytes($input,$kind);
                    $sub = $kind==='receipt' ? 'receipts/' : ($kind==='video' ? 'videos/' : '');
                    $filename=$sub.'erp-'.$operation.'-'.$digest.'.'.$ext;
                    $config=require __DIR__.'/config.php';
                    $path=rtrim($config['JOBS_PHOTOS_DIR'],'/').'/'.(int)$job['id'].'/'.$filename;
                    if (!is_dir(dirname($path)) && !mkdir(dirname($path),0755,true)) throw new RuntimeException('Storage unavailable');
                    if (is_file($path) && hash_file('sha256',$path)!==$digest) throw new RuntimeException('Storage conflict');
                    if (!is_file($path)) {
                        $temp=dirname($path).'/.ht-upload-'.bin2hex(random_bytes(10));
                        $written=$kind==='video' ? copy($videoPath,$temp) : file_put_contents($temp,$bytes,LOCK_EX)===strlen($bytes);
                        if (!$written || hash_file('sha256',$temp)!==$digest || !rename($temp,$path)) throw new RuntimeException('Upload unavailable');
                    }
                    $fields['filename']=$filename;
                    if ($kind!=='receipt') {
                        $fields['media_type']=$kind; $fields['client_photo_id']='ERP:'.$operation;
                        $fields['client_job_id']=$job['client_job_id'] ?: null;
                    }
                }
                $change=fm_change($db,$table,$before,$kind==='job' ? $fields : array_merge($fields,['job_id'=>(int)$job['id']]));
            }
            $changes[]=$change;
            if ($kind==='photo' && $mode==='add' && !empty($input['content_id'])) {
                $content=fm_row($db,'contents',(int)$input['content_id']);
                if (!$content || (int)$content['job_id']!==(int)$job['id']) throw new OutOfBoundsException('Contents item unavailable');
                $changes[]=fm_change($db,'content_photos',null,['content_id'=>(int)$content['id'],'photo_id'=>$change['id']]);
            }
            $result=['record_id'=>$change['id'],'kind'=>$kind,'mode'=>$mode,'replayed'=>false];
            if (isset($digest)) $result['sha256']=$digest;
            $plan=['fingerprint'=>$fingerprint,'status'=>'PREPARED','changes'=>$changes,'result'=>$result];
            fm_atomic_json($journal,$plan);
        }
        fm_apply_plan($db,$plan['changes']);
        $db->exec('COMMIT'); $transaction=false;
        $plan['status']='DONE'; fm_atomic_json($journal,$plan);
        if ($kind==='video' && $mode==='add') fm_video_cleanup($input);
        // Deleted rows remain in the private recovery journal; originals are retained.
        return $plan['result'];
    } finally {
        if ($transaction) $db->exec('ROLLBACK');
        flock($lock,LOCK_UN); fclose($lock);
    }
}

function fm_video_scope(array $input): string {
    return hash('sha256',json_encode([fm_text($input,'organization_id',100,true),fm_text($input,'workspace_id',100,true),
        fm_text($input,'portal_job_id',20,true),fm_text($input,'operation_id',36,true)],JSON_THROW_ON_ERROR));
}

function fm_video_cleanup(array $input): void {
    // Only discard private transport chunks after the hosted original and DB row
    // have been committed and journaled. Never touch the actual job video here.
    $key=fm_video_scope($input);
    for ($index=0;$index<25;$index++) {
        $path=fm_storage().'/video-'.$key.'-'.$index;
        if (is_file($path)) @unlink($path);
    }
    $path=fm_storage().'/video-'.$key.'-assembled';
    if (is_file($path)) @unlink($path);
}

function fm_video_chunk(PDO $db, array $input): array {
    fm_catalog_job($db,$input); $key=fm_video_scope($input);
    $index=$input['index'] ?? null; $total=$input['total'] ?? null;
    if (!is_int($index) || !is_int($total) || $index<0 || $index>24 || $total<1 || $total>25 || $index>=$total) throw new InvalidArgumentException('Invalid chunk');
    $bytes=base64_decode(fm_text($input,'chunk_base64',6*1024*1024,true),true);
    if ($bytes===false || strlen($bytes)>4*1024*1024 || !strlen($bytes)) throw new InvalidArgumentException('Invalid chunk');
    $digest=hash('sha256',$bytes);
    if (!hash_equals($digest,fm_text($input,'chunk_sha256',64,true))) throw new InvalidArgumentException('Checksum mismatch');
    $path=fm_storage().'/video-'.$key.'-'.$index;
    $lock=fopen(fm_storage().'/video.lock','c');
    if (!$lock || !flock($lock,LOCK_EX)) throw new RuntimeException('Portal busy');
    try {
        if (is_file($path) && hash_file('sha256',$path)!==$digest) throw new InvalidArgumentException('Chunk conflict');
        if (!is_file($path)) {
            $temp=$path.'.tmp';
            if (file_put_contents($temp,$bytes,LOCK_EX)!==strlen($bytes) || !rename($temp,$path)) throw new RuntimeException('Upload unavailable');
            chmod($path,0600);
        }
        return ['index'=>$index,'sha256'=>$digest];
    } finally { flock($lock,LOCK_UN); fclose($lock); }
}

function fm_video_commit(array $input): array {
    $key=fm_video_scope($input); $total=$input['total'] ?? null;
    if (!is_int($total) || $total<1 || $total>25) throw new InvalidArgumentException('Invalid video');
    $assembled=fm_storage().'/video-'.$key.'-assembled';
    $stream=fopen($assembled,'wb');
    if (!$stream) throw new RuntimeException('Storage unavailable');
    chmod($assembled,0600);
    for ($index=0;$index<$total;$index++) {
        $path=fm_storage().'/video-'.$key.'-'.$index;
        if (!is_file($path) || filesize($path)>4*1024*1024) { fclose($stream); throw new RuntimeException('Video is incomplete'); }
        $chunk=fopen($path,'rb'); $copied=stream_copy_to_stream($chunk,$stream); fclose($chunk);
        if ($copied!==filesize($path)) { fclose($stream); throw new RuntimeException('Upload unavailable'); }
    }
    fclose($stream); $digest=hash_file('sha256',$assembled);
    if (!hash_equals($digest,fm_text($input,'sha256',64,true))) throw new InvalidArgumentException('Checksum mismatch');
    $ext=fm_video_extension((string)file_get_contents($assembled,false,null,0,64));
    return [$assembled,$ext,$digest];
}

function fm_video_extension(string $head): string {
    if (substr($head,4,4)==='ftyp' && in_array(substr($head,8,4),['isom','iso2','mp41','mp42','avc1','M4V ','M4VH','M4VP','qt  '],true)) return substr($head,8,4)==='qt  ' ? 'mov' : 'mp4';
    if (str_starts_with($head,"\x1A\x45\xDF\xA3") && str_contains($head,'webm')) return 'webm';
    if (str_starts_with($head,'RIFF') && substr($head,8,4)==='AVI ') return 'avi';
    throw new InvalidArgumentException('Unsupported video');
}

function fm_staff_media(PDO $db, array $query): void {
    $job=(string)($query['key'] ?? ''); $asset=(string)($query['asset'] ?? '');
    if (!ctype_digit($job) || !ctype_digit($asset)) throw new InvalidArgumentException('Invalid asset');
    $receipt=$query['view']==='staff-receipt';
    $sql=$receipt ? 'SELECT filename FROM receipts WHERE id=? AND job_id=?' : "SELECT filename FROM photos WHERE id=? AND job_id=? AND media_type='video'";
    $statement=$db->prepare($sql); $statement->execute([(int)$asset,(int)$job]); $row=$statement->fetch();
    if (!$row) throw new OutOfBoundsException('Asset unavailable');
    $config=require __DIR__.'/config.php';
    $root=realpath(rtrim($config['JOBS_PHOTOS_DIR'],'/').'/'.(int)$job);
    $path=$root ? realpath($root.'/'.$row['filename']) : false;
    if (!$root || !$path || !str_starts_with($path,$root.DIRECTORY_SEPARATOR) || !is_file($path)) throw new OutOfBoundsException('Asset unavailable');
    if ($receipt) {
        $info=@getimagesize($path);
        if (!$info || !in_array($info['mime'],['image/jpeg','image/png','image/webp','image/gif'],true)) throw new OutOfBoundsException('Asset unavailable');
        fm_serve_file($path,$info['mime']); return;
    }
    $stream=fopen($path,'rb'); $ext=fm_video_extension((string)fread($stream,64));
    $type=['mp4'=>'video/mp4','mov'=>'video/quicktime','webm'=>'video/webm','avi'=>'video/x-msvideo'][$ext];
    $size=filesize($path); $start=0; $end=$size-1;
    $range=$_SERVER['HTTP_RANGE'] ?? '';
    if ($range!=='') {
        if (!preg_match('/^bytes=(\d*)-(\d*)$/D',$range,$parts) || ($parts[1]==='' && $parts[2]==='')) { http_response_code(416); header('Content-Range: bytes */'.$size); fclose($stream); return; }
        if ($parts[1]==='') $start=max(0,$size-(int)$parts[2]);
        else { $start=(int)$parts[1]; if ($parts[2]!=='') $end=min($end,(int)$parts[2]); }
        if ($start>$end || $start>=$size) { http_response_code(416); header('Content-Range: bytes */'.$size); fclose($stream); return; }
        http_response_code(206); header("Content-Range: bytes $start-$end/$size");
    }
    header('Accept-Ranges: bytes'); header('Content-Type: '.$type); header('Content-Length: '.($end-$start+1));
    fseek($stream,$start); $remaining=$end-$start+1;
    while ($remaining>0 && !feof($stream)) { $chunk=fread($stream,min(65536,$remaining)); echo $chunk; $remaining-=strlen($chunk); }
    fclose($stream);
}
