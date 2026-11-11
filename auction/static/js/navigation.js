(() => {
  const body = document.body;
  const openButtons = document.querySelectorAll('[data-sidebar-open]');
  const closeButtons = document.querySelectorAll('[data-sidebar-close]');
  const collapseButton = document.querySelector('[data-sidebar-collapse]');
  const drawerLinks = document.querySelectorAll('#appSidebar a[href]');
  const profileToggle = document.querySelector('[data-app-profile-toggle]');
  const profileMenu = document.querySelector('[data-app-profile-menu]');
  const desktopQuery = window.matchMedia('(min-width: 768px)');
  const storageKey = 'auctionhub-sidebar-collapsed';

  const readCollapsed = () => {
    try {
      return localStorage.getItem(storageKey) === 'true';
    } catch (_) {
      return false;
    }
  };

  const setDrawer = (open) => {
    body.classList.toggle('sidebar-open', open && !desktopQuery.matches);
    openButtons.forEach((button) => button.setAttribute('aria-expanded', String(open && !desktopQuery.matches)));
  };

  const setCollapsed = (collapsed, persist = false) => {
    body.classList.toggle('sidebar-collapsed', collapsed && desktopQuery.matches);
    if (collapseButton) {
      const expanded = !collapsed || !desktopQuery.matches;
      collapseButton.setAttribute('aria-expanded', String(expanded));
      collapseButton.setAttribute('aria-label', expanded ? 'Collapse sidebar' : 'Expand sidebar');
      collapseButton.title = expanded ? 'Collapse sidebar' : 'Expand sidebar';
    }
    if (persist) {
      try {
        localStorage.setItem(storageKey, String(collapsed));
      } catch (_) {
        // The sidebar still works for this page when storage is unavailable.
      }
    }
  };

  openButtons.forEach((button) => button.addEventListener('click', () => setDrawer(true)));
  closeButtons.forEach((button) => button.addEventListener('click', () => setDrawer(false)));
  drawerLinks.forEach((link) => link.addEventListener('click', () => {
    if (!desktopQuery.matches) setDrawer(false);
  }));
  collapseButton?.addEventListener('click', () => {
    setCollapsed(!body.classList.contains('sidebar-collapsed'), true);
  });

  profileToggle?.addEventListener('click', () => {
    const open = profileMenu?.hasAttribute('hidden') ?? false;
    if (!profileMenu) return;
    profileMenu.toggleAttribute('hidden', !open);
    profileToggle.setAttribute('aria-expanded', String(open));
  });
  document.addEventListener('click', (event) => {
    if (profileMenu && !profileMenu.hasAttribute('hidden') && !event.target.closest('.app-profile-menu')) {
      profileMenu.setAttribute('hidden', '');
      profileToggle?.setAttribute('aria-expanded', 'false');
    }
  });

  const syncViewport = () => {
    setDrawer(false);
    setCollapsed(desktopQuery.matches && readCollapsed());
  };
  syncViewport();
  desktopQuery.addEventListener('change', syncViewport);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      setDrawer(false);
      profileMenu?.setAttribute('hidden', '');
      profileToggle?.setAttribute('aria-expanded', 'false');
    }
  });
})();
