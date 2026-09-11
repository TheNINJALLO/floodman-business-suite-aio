<?php
/**
 * Layout Shell - Provides the professional app structure with sidebar navigation
 *
 * Usage:
 *   require_once __DIR__ . '/layout.php';
 *   $layout = new Layout($auth);
 *   $layout->setTitle('Page Title');
 *   $layout->setBreadcrumbs([['label' => 'Home', 'url' => 'index.php'], ['label' => 'Current']]);
 *   $layout->setActivePage('jobs'); // jobs, new_job, employees, import
 *   echo $layout->start();
 *   // ... page content ...
 *   echo $layout->end();
 */

class Layout {
    private $auth;
    private $title = 'Floodman Portal';
    private $breadcrumbs = [];
    private $activePage = 'jobs';

    public function __construct($auth) {
        $this->auth = $auth;
    }

    public function setTitle($title) {
        $this->title = $title . ' - Floodman Portal';
        return $this;
    }

    public function setBreadcrumbs($breadcrumbs) {
        $this->breadcrumbs = $breadcrumbs;
        return $this;
    }

    public function setActivePage($page) {
        $this->activePage = $page;
        return $this;
    }

    private function isActive($page) {
        return $this->activePage === $page ? 'active' : '';
    }

    public function start() {
        $userName = htmlspecialchars($this->auth->getUserName());
        $isAdmin = $this->auth->isAdmin();

        $breadcrumbHtml = '';
        foreach ($this->breadcrumbs as $i => $crumb) {
            if ($i > 0) {
                $breadcrumbHtml .= '<span class="breadcrumb-sep">›</span>';
            }
            if (isset($crumb['url'])) {
                $breadcrumbHtml .= '<a href="' . $crumb['url'] . '" class="breadcrumb-link">' . htmlspecialchars($crumb['label']) . '</a>';
            } else {
                $breadcrumbHtml .= '<span class="breadcrumb-current">' . htmlspecialchars($crumb['label']) . '</span>';
            }
        }

        ob_start();
        ?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <meta name="theme-color" content="#07111f">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="Floodman">
    <title><?= htmlspecialchars($this->title) ?></title>
    <link rel="stylesheet" href="assets/style.css">
    <link rel="stylesheet" href="assets/floodman-erp.css?v=20260911">
    <link rel="manifest" href="manifest.json">
    <link rel="apple-touch-icon" href="assets/icons/icon-192.png">
    <link rel="icon" type="image/png" sizes="192x192" href="assets/icons/icon-192.png">
</head>
<body class="app-layout">
    <!-- Sidebar Overlay (mobile) -->
    <div class="sidebar-overlay" id="sidebar-overlay"></div>

    <!-- Sidebar Navigation -->
    <aside class="app-sidebar" id="app-sidebar">
        <div class="sidebar-header">
            <div class="sidebar-logo">
                <span class="logo-icon" aria-hidden="true">F</span>
                <span class="logo-text">FLOODMAN</span>
            </div>
        </div>

        <nav class="sidebar-nav">
            <div class="nav-group">
                <div class="nav-group-label">Operations</div>
                <a href="https://floodman.oninetwork.com/office/photo-portal" class="nav-item"><span class="nav-label">Back to ERP</span></a>
                <a href="index.php" class="nav-item <?= $this->isActive('jobs') ?>">
                    <span class="nav-icon">🏠</span>
                    <span class="nav-label">Jobs</span>
                </a>
                <a href="new_job.php" class="nav-item <?= $this->isActive('new_job') ?>">
                    <span class="nav-icon">➕</span>
                    <span class="nav-label">New Job</span>
                </a>
            </div>

            <?php if ($isAdmin): ?>
            <div class="nav-group">
                <div class="nav-group-label">Admin</div>
                <a href="employees.php" class="nav-item <?= $this->isActive('employees') ?>">
                    <span class="nav-icon">👥</span>
                    <span class="nav-label">Team</span>
                </a>
                <a href="import.php" class="nav-item <?= $this->isActive('import') ?>">
                    <span class="nav-icon">📥</span>
                    <span class="nav-label">Import</span>
                </a>
            </div>
            <?php endif; ?>
        </nav>

        <div class="sidebar-footer">
            <small class="creator-credit">Created by Josh Aldrich</small>
            <div class="sidebar-user">
                <div class="user-avatar"><?= strtoupper(substr($userName, 0, 1)) ?></div>
                <div class="user-info">
                    <span class="user-name"><?= $userName ?></span>
                    <span class="user-role"><?= $isAdmin ? 'Administrator' : 'Employee' ?></span>
                </div>
            </div>
            <a href="logout.php" class="nav-item nav-logout">
                <span class="nav-icon">🚪</span>
                <span class="nav-label">Logout</span>
            </a>
        </div>
    </aside>

    <!-- Main Content Area -->
    <div class="app-main">
        <!-- Top Header -->
        <header class="app-header">
            <div class="header-left">
                <button type="button" class="hamburger-btn" id="hamburger-btn" aria-label="Toggle menu">
                    <span></span>
                    <span></span>
                    <span></span>
                </button>
                <div class="header-breadcrumb">
                    <?= $breadcrumbHtml ?>
                </div>
            </div>
            <div class="header-right">
                <div class="header-user-dropdown" id="user-dropdown">
                    <button type="button" class="user-dropdown-btn">
                        <span class="user-avatar-small"><?= strtoupper(substr($userName, 0, 1)) ?></span>
                        <span class="user-name-text"><?= $userName ?></span>
                        <span class="dropdown-arrow">▼</span>
                    </button>
                    <div class="user-dropdown-menu">
                        <a href="logout.php" class="dropdown-item">🚪 Logout</a>
                    </div>
                </div>
            </div>
        </header>

        <!-- Page Content -->
        <main class="app-content">
            <!-- Global Pending Uploads Banner -->
            <div id="global-sync-banner" class="global-sync-banner hidden" style="background: #e67e22; color: white; padding: 12px 20px; border-radius: 8px; margin-bottom: 20px; display: none; align-items: center; justify-content: space-between; font-weight: 500; box-shadow: 0 2px 5px rgba(0,0,0,0.1);">
                <div style="display: flex; align-items: center; gap: 10px;">
                    <span>⚠️</span>
                    <span id="global-sync-message">You have pending photos waiting to upload.</span>
                </div>
                <button type="button" onclick="if(window.OfflinePhotos) window.OfflinePhotos.sync()" class="btn" style="background: white; color: #e67e22; border: none; padding: 6px 12px; border-radius: 6px; font-weight: bold; cursor: pointer; transition: opacity 0.2s;">Sync Now</button>
            </div>
        <?php
        return ob_get_clean();
    }

    public function end() {
        ob_start();
        ?>
        </main>
    </div>

    <script>
    // Sidebar Toggle
    const sidebar = document.getElementById('app-sidebar');
    const overlay = document.getElementById('sidebar-overlay');
    const hamburger = document.getElementById('hamburger-btn');

    function toggleSidebar() {
        sidebar.classList.toggle('open');
        overlay.classList.toggle('visible');
        document.body.classList.toggle('sidebar-open');
    }

    hamburger.addEventListener('click', toggleSidebar);
    overlay.addEventListener('click', toggleSidebar);

    // Close sidebar on navigation on mobile
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            if (window.innerWidth < 1024) {
                sidebar.classList.remove('open');
                overlay.classList.remove('visible');
                document.body.classList.remove('sidebar-open');
            }
        });
    });

    // User Dropdown
    const userDropdown = document.getElementById('user-dropdown');
    userDropdown.querySelector('.user-dropdown-btn').addEventListener('click', function(e) {
        e.stopPropagation();
        userDropdown.classList.toggle('open');
    });

    document.addEventListener('click', () => {
        userDropdown.classList.remove('open');
    });

    // Register Service Worker for PWA
    if ('serviceWorker' in navigator) {
        window.addEventListener('load', () => {
            navigator.serviceWorker.register('sw.js')
                .then(reg => console.log('SW registered:', reg.scope))
                .catch(err => console.log('SW registration failed:', err));
        });
    }
    </script>
    <script src="assets/capacitor-bridge.js"></script>
    <script src="assets/offline-uploads.js"></script>
    <script>
    // Listen for offline status events and update global banner
    window.addEventListener('offline-sync-status', function(e) {
        const banner = document.getElementById('global-sync-banner');
        const message = document.getElementById('global-sync-message');
        if (!banner) return;

        const pendingPhotos = e.detail.pendingPhotosCount || 0;
        const pendingJobs = e.detail.pendingJobsCount || 0;
        const total = pendingPhotos + pendingJobs;

        if (total > 0) {
            banner.classList.remove('hidden');
            banner.style.display = 'flex';
            if (pendingJobs > 0) {
                message.textContent = `You have ${pendingJobs} job draft(s) and ${pendingPhotos} photo(s) waiting to upload.`;
            } else {
                message.textContent = `You have ${pendingPhotos} photo(s) waiting to upload.`;
            }
        } else {
            banner.classList.add('hidden');
            banner.style.display = 'none';
        }
    });
    </script>
        <?php
        return ob_get_clean();
    }
}
?>
