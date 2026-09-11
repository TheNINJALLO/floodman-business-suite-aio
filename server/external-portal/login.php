<?php
/**
 * Login Page
 */
require_once __DIR__ . '/includes/auth.php';

$auth = getAuth();

// Redirect if already logged in
if ($auth->isLoggedIn()) {
    header('Location: index.php');
    exit;
}

$error = '';

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $username = trim($_POST['username'] ?? '');
    $password = $_POST['password'] ?? '';

    if ($auth->login($username, $password)) {
        header('Location: index.php');
        exit;
    } else {
        $error = 'Invalid username or password';
    }
}
?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <title>Floodman Portal - Login</title>
    <link rel="stylesheet" href="assets/style.css">
    <link rel="stylesheet" href="assets/floodman-erp.css?v=20260911">
</head>
<body class="login-page">
    <div class="login-container">
        <div class="login-logo">
            <h1>FLOODMAN</h1>
            <p>Photo Portal</p>
            <a class="btn btn-primary btn-full" href="https://floodman.oninetwork.com/office/photo-portal">Open through Floodman ERP</a>
            <p class="creator-credit">Created by Josh Aldrich</p>
        </div>

        <?php if ($error): ?>
            <div class="alert alert-error"><?= htmlspecialchars($error) ?></div>
        <?php endif; ?>

        <form method="POST" class="login-form">
            <div class="form-group">
                <label for="username">Username</label>
                <input type="text" id="username" name="username" required autofocus autocomplete="username">
            </div>

            <div class="form-group">
                <label for="password">Password</label>
                <input type="password" id="password" name="password" required autocomplete="current-password">
            </div>

            <button type="submit" class="btn btn-primary btn-full">Sign In</button>
        </form>
    </div>
</body>
</html>
