/**
 * 全局 UI 工具库
 * 统一管理 Toast、Modal、通知等 UI 组件
 */
const UI = {
  // ==================== Toast ====================
  _toastTimer: null,

  showToast(message, type = 'info', duration = 3000) {
    const existing = document.querySelector('.global-toast');
    if (existing) existing.remove();
    if (this._toastTimer) clearTimeout(this._toastTimer);

    const icons = {
      success: '✓',
      error: '✕',
      warning: '⚠',
      info: 'ℹ',
    };

    const toast = document.createElement('div');
    toast.className = `global-toast ${type}`;
    toast.style.cssText = `
      position: fixed; top: 20px; right: 20px; z-index: 2000;
      display: flex; align-items: center; gap: 10px;
      padding: 12px 20px; border-radius: 8px;
      font-size: 14px; font-weight: 500;
      background: var(--card-bg, #fff); color: var(--text-color, #333);
      box-shadow: 0 4px 12px rgba(0,0,0,0.15);
      transform: translateX(120%); opacity: 0;
      transition: transform 0.3s ease, opacity 0.3s ease;
      max-width: 400px; word-break: break-word;
    `;

    const colors = {
      success: { bg: '#ecfdf5', border: '#10b981', text: '#065f46' },
      error: { bg: '#fef2f2', border: '#ef4444', text: '#991b1b' },
      warning: { bg: '#fffbeb', border: '#f59e0b', text: '#92400e' },
      info: { bg: '#eff6ff', border: '#3b82f6', text: '#1e40af' },
    };

    const c = colors[type] || colors.info;
    toast.style.background = c.bg;
    toast.style.borderLeft = `4px solid ${c.border}`;
    toast.style.color = c.text;

    toast.innerHTML = `<span style="font-size:18px;font-weight:700;flex-shrink:0;">${icons[type] || 'ℹ'}</span><span>${message}</span>`;

    document.body.appendChild(toast);
    requestAnimationFrame(() => {
      toast.style.transform = 'translateX(0)';
      toast.style.opacity = '1';
    });

    this._toastTimer = setTimeout(() => {
      toast.style.transform = 'translateX(120%)';
      toast.style.opacity = '0';
      setTimeout(() => toast.remove(), 300);
    }, duration);
  },

  toast: {
    success: (msg, dur) => UI.showToast(msg, 'success', dur),
    error: (msg, dur) => UI.showToast(msg, 'error', dur),
    warning: (msg, dur) => UI.showToast(msg, 'warning', dur),
    info: (msg, dur) => UI.showToast(msg, 'info', dur),
  },

  // ==================== Modal ====================
  showModal(options = {}) {
    const { title, content, confirmText = '确定', cancelText = '取消', 
            onConfirm, onCancel, width = '400px', showCancel = true } = options;

    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.style.cssText = `
      position: fixed; inset: 0; z-index: 1000;
      background: rgba(0,0,0,0.5); display: flex;
      align-items: center; justify-content: center;
      animation: fadeIn 0.2s ease;
    `;

    overlay.innerHTML = `
      <div class="modal-content" style="
        background: var(--card-bg,#fff); border-radius: 12px;
        width: ${width}; max-width: 90vw; max-height: 80vh;
        overflow-y: auto; padding: 24px;
        box-shadow: 0 8px 24px rgba(0,0,0,0.12);
      ">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
          <h3 style="margin:0;font-size:18px;color:var(--text-color,#333);">${title}</h3>
          <button class="modal-close-btn" style="background:none;border:none;font-size:20px;cursor:pointer;color:var(--text-secondary,#666);padding:4px;">✕</button>
        </div>
        <div style="color:var(--text-color,#333);font-size:14px;line-height:1.6;">${content}</div>
        <div style="display:flex;justify-content:flex-end;gap:12px;margin-top:20px;">
          ${showCancel ? `<button class="modal-btn secondary" style="padding:8px 20px;border-radius:8px;border:1px solid var(--border-color,#e0e0e0);background:var(--card-bg,#fff);color:var(--text-color,#333);cursor:pointer;">${cancelText}</button>` : ''}
          <button class="modal-btn primary" style="padding:8px 20px;border-radius:8px;border:none;background:var(--primary-color,#667eea);color:#fff;cursor:pointer;">${confirmText}</button>
        </div>
      </div>
    `;

    document.body.appendChild(overlay);

    // 绑定事件
    const contentEl = overlay.querySelector('.modal-content');
    const closeBtn = overlay.querySelector('.modal-close-btn');
    const confirmBtn = overlay.querySelector('.modal-btn.primary');
    const cancelBtn = overlay.querySelector('.modal-btn.secondary');

    const close = (result) => {
      overlay.style.animation = 'fadeIn 0.2s ease reverse';
      setTimeout(() => overlay.remove(), 200);
      if (result && onConfirm) onConfirm();
      else if (!result && onCancel) onCancel();
    };

    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) close(false);
    });
    closeBtn?.addEventListener('click', () => close(false));
    confirmBtn?.addEventListener('click', () => close(true));
    cancelBtn?.addEventListener('click', () => close(false));
  },

  // ==================== 确认对话框 ====================
  confirm(message, title = '确认') {
    return new Promise((resolve) => {
      this.showModal({
        title,
        content: `<p style="text-align:center;font-size:15px;">${message}</p>`,
        confirmText: '确定',
        cancelText: '取消',
        onConfirm: () => resolve(true),
        onCancel: () => resolve(false),
        width: '360px',
      });
    });
  },

  // ==================== 桌面通知 ====================
  notify(title, body, icon) {
    if (!('Notification' in window)) return;
    if (Notification.permission === 'granted') {
      new Notification(title, { body, icon });
    } else if (Notification.permission !== 'denied') {
      Notification.requestPermission().then(p => {
        if (p === 'granted') new Notification(title, { body, icon });
      });
    }
  },
};

// 暴露全局
window.UI = UI;
