/* ====================================================================
 * P0 核心功能前端模块
 * - 手机号绑定引导弹窗
 * - 好友申请模块 Tab
 * - 个人资料表单(状态管理)
 * - 账户注销 UI
 * ====================================================================
 * 数据来源: 后端 API
 *   /api/profile/completeness, /api/profile/me/dismiss-phone-reminder
 *   /api/profile/me, /api/profile/me/phone
 *   /api/friendship/requests/inbox, /api/friendship/requests/sent
 *   /api/friendship/requests, /api/friendship/requests/process
 *   /api/friendship/check/{user_id}
 *   /api/account/cancel, /api/account/deletion-status, /api/account/restore
 * ====================================================================
 */

(function() {
    'use strict';

    const API_BASE = window.API_BASE || '';
    const ROLE = window.ROLE || 'client';

    // ============================
    // 工具函数
    // ============================
    async function apiRequest(url, options = {}) {
        const token = localStorage.getItem('rag-auth-token') || localStorage.getItem('auth_token') || '';
        const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
        if (token) headers['Authorization'] = `Bearer ${token}`;
        try {
            const resp = await fetch(`${API_BASE}${url}`, {
                ...options,
                headers,
                body: options.body && typeof options.body !== 'string' ? JSON.stringify(options.body) : options.body,
            });
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({ detail: resp.statusText }));
                throw new Error(err.detail || `HTTP ${resp.status}`);
            }
            return await resp.json();
        } catch (e) {
            console.error('[P0] API请求失败:', url, e);
            throw e;
        }
    }

    function showToast(message, type = 'info') {
        // 复用已有的showToast或简单实现
        if (typeof window.showToast === 'function') {
            window.showToast(message, type);
        } else {
            console.log(`[Toast ${type}] ${message}`);
            alert(message);
        }
    }

    function escapeHtml(s) {
        if (s == null) return '';
        return String(s).replace(/[&<>"']/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[c]));
    }

    // ============================
    // 1. 手机号绑定引导弹窗
    // ============================
    const PhoneBindingDialog = {
        shown: false,

        async shouldShow() {
            try {
                const data = await apiRequest('/api/profile/completeness');
                return !data.phone_bound;
            } catch (e) {
                return false;
            }
        },

        async show() {
            if (this.shown) return;
            this.shown = true;

            // 移除旧弹窗
            const old = document.getElementById('p0-phone-dialog');
            if (old) old.remove();

            const html = `
                <div id="p0-phone-dialog" style="position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;display:flex;align-items:center;justify-content:center;">
                    <div style="background:#fff;border-radius:12px;padding:24px;width:380px;max-width:90%;box-shadow:0 10px 40px rgba(0,0,0,.2);">
                        <h3 style="margin:0 0 12px;font-size:18px;color:#1f2937;">📱 绑定手机号</h3>
                        <p style="margin:0 0 16px;color:#6b7280;font-size:14px;line-height:1.5;">
                            为了使用好友添加、消息推送等社交功能,请先绑定手机号。
                        </p>
                        <input id="p0-phone-input" type="text" maxlength="11"
                               placeholder="请输入11位手机号"
                               style="width:100%;padding:10px 12px;border:1px solid #d1d5db;border-radius:6px;font-size:14px;box-sizing:border-box;" />
                        <div id="p0-phone-error" style="color:#ef4444;font-size:12px;margin-top:6px;min-height:18px;"></div>
                        <div style="display:flex;gap:8px;margin-top:16px;">
                            <button id="p0-phone-skip" style="flex:1;padding:10px;background:#f3f4f6;color:#374151;border:none;border-radius:6px;cursor:pointer;font-size:14px;">暂不绑定</button>
                            <button id="p0-phone-confirm" style="flex:1;padding:10px;background:#3b82f6;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:14px;">立即绑定</button>
                        </div>
                    </div>
                </div>
            `;
            const div = document.createElement('div');
            div.innerHTML = html;
            document.body.appendChild(div.firstElementChild);

            document.getElementById('p0-phone-skip').onclick = async () => {
                try {
                    await apiRequest('/api/profile/me/dismiss-phone-reminder', { method: 'POST' });
                    showToast('已记住,24小时内不再提醒', 'info');
                } catch (e) {
                    console.warn('关闭提醒失败:', e);
                }
                this.close();
            };

            document.getElementById('p0-phone-confirm').onclick = async () => {
                const phone = document.getElementById('p0-phone-input').value.trim();
                const errEl = document.getElementById('p0-phone-error');
                if (!/^\d{11}$/.test(phone)) {
                    errEl.textContent = '请输入正确的11位手机号';
                    return;
                }
                try {
                    await apiRequest('/api/profile/me/phone', {
                        method: 'PUT',
                        body: JSON.stringify({ phone }),
                    });
                    showToast('手机号绑定成功!', 'success');
                    this.close();
                    if (typeof window.loadProfile === 'function') window.loadProfile();
                } catch (e) {
                    errEl.textContent = e.message || '绑定失败';
                }
            };
        },

        close() {
            const el = document.getElementById('p0-phone-dialog');
            if (el) el.remove();
            this.shown = false;
        },

        async autoCheck() {
            if (this.shown) return;
            const should = await this.shouldShow();
            if (should) {
                // 延迟1秒,避免页面刚加载就弹
                setTimeout(() => this.show(), 1000);
            }
        },
    };

    // ============================
    // 2. 好友申请模块(联系人Tab内部)
    // ============================
    const FriendRequestsModule = {
        activeTab: 'received', // received / sent

        async load() {
            try {
                const data = await apiRequest('/api/friendship/requests/inbox');
                this.render(data);
            } catch (e) {
                console.error('[好友申请] 加载失败:', e);
            }
        },

        render(data) {
            const container = document.getElementById('friend-requests-container');
            if (!container) return;

            const received = data.received || [];
            const sent = data.sent || [];
            const active = this.activeTab;
            const list = active === 'received' ? received : sent;

            container.innerHTML = `
                <div class="freq-tabs">
                    <button class="freq-tab ${active==='received'?'active':''}" data-tab="received">
                        收到的申请 ${received.length > 0 ? `(${received.length})` : ''}
                    </button>
                    <button class="freq-tab ${active==='sent'?'active':''}" data-tab="sent">
                        我发出的 ${sent.length > 0 ? `(${sent.length})` : ''}
                    </button>
                </div>
                <div class="freq-list">
                    ${list.length === 0
                        ? `<div class="freq-empty">暂无${active==='received'?'收到':'发出'}的申请</div>`
                        : list.map(r => this.renderItem(r)).join('')
                    }
                </div>
            `;

            // 绑定tab切换
            container.querySelectorAll('.freq-tab').forEach(btn => {
                btn.onclick = () => {
                    this.activeTab = btn.dataset.tab;
                    this.load();
                };
            });

            // 绑定按钮事件
            container.querySelectorAll('[data-freq-action]').forEach(btn => {
                btn.onclick = () => this.handleAction(btn.dataset.freqAction, btn.dataset);
            });
        },

        renderItem(r) {
            const name = escapeHtml(r.other_display_name || r.other_username);
            const roleText = r.other_role === 'consultant' ? '规划师' : '用户';
            const initial = (r.other_display_name || r.other_username || '?')[0];

            if (r.direction === 'received') {
                return `
                    <div class="freq-item">
                        <div class="freq-avatar">${escapeHtml(initial)}</div>
                        <div class="freq-info">
                            <div class="freq-name">${name} <span class="freq-role">${roleText}</span></div>
                            ${r.message ? `<div class="freq-msg">"${escapeHtml(r.message)}"</div>` : ''}
                            <div class="freq-time">${new Date(r.created_at).toLocaleString('zh-CN')}</div>
                        </div>
                        <div class="freq-actions">
                            <button class="freq-btn freq-accept" data-freq-action="accept" data-id="${r.id}">接受</button>
                            <button class="freq-btn freq-reject" data-freq-action="reject" data-id="${r.id}">拒绝</button>
                        </div>
                    </div>
                `;
            } else {
                const statusMap = {
                    pending: '<span class="freq-status pending">待处理</span>',
                    accepted: '<span class="freq-status accepted">已通过</span>',
                    rejected: '<span class="freq-status rejected">已拒绝</span>',
                };
                return `
                    <div class="freq-item">
                        <div class="freq-avatar">${escapeHtml(initial)}</div>
                        <div class="freq-info">
                            <div class="freq-name">${name} <span class="freq-role">${roleText}</span></div>
                            ${r.message ? `<div class="freq-msg">"${escapeHtml(r.message)}"</div>` : ''}
                            <div class="freq-time">${new Date(r.created_at).toLocaleString('zh-CN')}</div>
                        </div>
                        <div class="freq-status-wrap">${statusMap[r.status] || r.status}</div>
                    </div>
                `;
            }
        },

        async handleAction(action, dataset) {
            const requestId = dataset.id;
            if (!confirm(action === 'accept' ? '确定接受好友申请?' : '确定拒绝好友申请?')) return;
            try {
                await apiRequest('/api/friendship/requests/process', {
                    method: 'POST',
                    body: JSON.stringify({ request_id: requestId, action }),
                });
                showToast(action === 'accept' ? '已接受好友申请' : '已拒绝', 'success');
                this.load();
            } catch (e) {
                showToast('操作失败: ' + e.message, 'error');
            }
        },
    };

    // ============================
    // 3. 个人资料表单(状态管理)
    // ============================
    const ProfileForm = {
        state: {
            profile: {},
            completeness: { score: 0, missing_required: [], missing_optional: [] },
            formData: {},
            isDirty: false,
            saving: false,
        },

        async load() {
            try {
                const [profile, completeness] = await Promise.all([
                    apiRequest('/api/profile/me'),
                    apiRequest('/api/profile/completeness'),
                ]);
                this.state.profile = profile;
                this.state.completeness = completeness;
                this.state.formData = { ...profile };
                this.state.isDirty = false;
                this.render();
            } catch (e) {
                console.error('[个人资料] 加载失败:', e);
                showToast('加载资料失败: ' + e.message, 'error');
            }
        },

        updateField(field, value) {
            this.state.formData[field] = value;
            this.state.isDirty = true;
            this.renderSaveButton();
        },

        async save() {
            if (this.state.saving) return;
            this.state.saving = true;
            this.renderSaveButton();
            try {
                const updated = await apiRequest('/api/profile/me', {
                    method: 'PUT',
                    body: JSON.stringify(this.state.formData),
                });
                this.state.profile = updated;
                this.state.formData = { ...updated };
                this.state.isDirty = false;
                // 重新加载完整度
                const completeness = await apiRequest('/api/profile/completeness');
                this.state.completeness = completeness;
                showToast('保存成功!', 'success');
                this.render();
            } catch (e) {
                showToast('保存失败: ' + e.message, 'error');
            } finally {
                this.state.saving = false;
                this.renderSaveButton();
            }
        },

        renderSaveButton() {
            const btn = document.getElementById('profile-save-btn');
            if (!btn) return;
            btn.disabled = !this.state.isDirty || this.state.saving;
            btn.textContent = this.state.saving ? '保存中...' : (this.state.isDirty ? '保存修改' : '已保存');
            btn.style.opacity = (this.state.isDirty && !this.state.saving) ? '1' : '0.5';
        },

        render() {
            const container = document.getElementById('profile-form-container');
            if (!container) return;
            const p = this.state.formData;
            const c = this.state.completeness;

            container.innerHTML = `
                <div class="profile-completeness">
                    <div class="pc-bar"><div class="pc-fill" style="width:${c.completeness}%"></div></div>
                    <div class="pc-text">资料完整度: <strong>${c.completeness}%</strong>
                        ${c.missing_required.length > 0
                            ? `<span style="color:#ef4444;margin-left:8px;">缺失: ${c.missing_required.join(', ')}</span>`
                            : ''}
                    </div>
                </div>

                <div class="profile-section">
                    <h4>基础信息</h4>
                    <div class="profile-field">
                        <label>昵称</label>
                        <input type="text" data-field="nickname" value="${escapeHtml(p.nickname || '')}" />
                    </div>
                    <div class="profile-field">
                        <label>真实姓名 <span class="required">*</span></label>
                        <input type="text" data-field="real_name" value="${escapeHtml(p.real_name || '')}" />
                    </div>
                    <div class="profile-field">
                        <label>性别</label>
                        <select data-field="gender">
                            <option value="保密" ${p.gender==='保密'?'selected':''}>保密</option>
                            <option value="男" ${p.gender==='男'?'selected':''}>男</option>
                            <option value="女" ${p.gender==='女'?'selected':''}>女</option>
                        </select>
                    </div>
                    <div class="profile-field">
                        <label>所在城市</label>
                        <input type="text" data-field="city" value="${escapeHtml(p.city || '')}" />
                    </div>
                    <div class="profile-field">
                        <label>个人简介</label>
                        <textarea data-field="bio" rows="3">${escapeHtml(p.bio || '')}</textarea>
                    </div>
                </div>

                <div class="profile-section">
                    <h4>手机号</h4>
                    <div class="profile-field">
                        <label>已绑定手机号</label>
                        <div style="display:flex;gap:8px;align-items:center;">
                            <input type="text" id="profile-phone-input" value="${escapeHtml(p.phone || '')}"
                                   placeholder="未绑定" maxlength="11" style="flex:1;" />
                            <button id="profile-phone-btn" style="padding:8px 16px;background:#10b981;color:#fff;border:none;border-radius:6px;cursor:pointer;">
                                ${p.phone ? '更新' : '绑定'}
                            </button>
                        </div>
                    </div>
                </div>

                ${ROLE === 'client' ? `
                <div class="profile-section">
                    <h4>留学意向</h4>
                    <div class="profile-field">
                        <label>目标国家 <span class="required">*</span></label>
                        <input type="text" data-field="target_country" value="${escapeHtml(p.target_country || '')}" />
                    </div>
                    <div class="profile-field">
                        <label>目标阶段</label>
                        <input type="text" data-field="target_level" value="${escapeHtml(p.target_level || '')}"
                               placeholder="本科/硕士/博士" />
                    </div>
                    <div class="profile-field">
                        <label>语言成绩</label>
                        <input type="text" data-field="language_score" value="${escapeHtml(p.language_score || '')}"
                               placeholder="如:TOEFL 100" />
                    </div>
                    <div class="profile-field">
                        <label>教育背景</label>
                        <input type="text" data-field="education" value="${escapeHtml(p.education || '')}" />
                    </div>
                </div>
                ` : `
                <div class="profile-section">
                    <h4>规划师专属</h4>
                    <div class="profile-field">
                        <label>规划师简介 <span class="required">*</span></label>
                        <textarea data-field="consultant_bio" rows="3">${escapeHtml(p.consultant_bio || '')}</textarea>
                    </div>
                    <div class="profile-field">
                        <label>专长领域 <span class="required">*</span>(逗号分隔)</label>
                        <input type="text" data-field="expertise_areas_str"
                               value="${escapeHtml((p.expertise_areas || []).join(', '))}" />
                    </div>
                    <div class="profile-field">
                        <label>服务价格</label>
                        <input type="text" data-field="service_price" value="${escapeHtml(p.service_price || '')}" />
                    </div>
                </div>
                `}

                <div class="profile-actions">
                    <button id="profile-save-btn" disabled>已保存</button>
                </div>
            `;

            // 绑定事件
            container.querySelectorAll('[data-field]').forEach(el => {
                el.oninput = () => {
                    const field = el.dataset.field;
                    let value = el.value;
                    if (field === 'expertise_areas_str') {
                        // 转换为数组
                        this.updateField('expertise_areas', value.split(/[,，]/).map(s => s.trim()).filter(Boolean));
                    } else {
                        this.updateField(field, value);
                    }
                };
            });

            // 手机号按钮
            const phoneBtn = document.getElementById('profile-phone-btn');
            if (phoneBtn) {
                phoneBtn.onclick = async () => {
                    const phone = document.getElementById('profile-phone-input').value.trim();
                    if (!/^\d{11}$/.test(phone)) {
                        showToast('请输入正确的11位手机号', 'error');
                        return;
                    }
                    try {
                        await apiRequest('/api/profile/me/phone', {
                            method: 'PUT',
                            body: JSON.stringify({ phone }),
                        });
                        showToast('手机号已' + (p.phone ? '更新' : '绑定'), 'success');
                        this.load();
                    } catch (e) {
                        showToast('操作失败: ' + e.message, 'error');
                    }
                };
            }

            // 保存按钮
            const saveBtn = document.getElementById('profile-save-btn');
            if (saveBtn) saveBtn.onclick = () => this.save();
            this.renderSaveButton();
        },

        /** AI可调用：打开个人资料编辑弹窗 */
        show() {
            let dialog = document.getElementById('p0-profile-dialog-ai');
            if (!dialog) {
                dialog = document.createElement('div');
                dialog.id = 'p0-profile-dialog-ai';
                dialog.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;display:flex;align-items:center;justify-content:center;';
                dialog.innerHTML = `
                    <div style="background:#fff;border-radius:12px;padding:24px;width:520px;max-width:90%;max-height:85vh;overflow-y:auto;box-shadow:0 10px 40px rgba(0,0,0,.2);">
                        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
                            <h3 style="margin:0;font-size:18px;">👤 个人资料</h3>
                            <button id="p0-profile-dialog-ai-close" style="background:none;border:none;font-size:20px;cursor:pointer;color:#666;">✕</button>
                        </div>
                        <div id="profile-form-container"></div>
                    </div>`;
                dialog.addEventListener('click', function(e) { if (e.target === this) this.remove(); });
                document.body.appendChild(dialog);
                document.getElementById('p0-profile-dialog-ai-close').onclick = () => dialog.remove();
            }
            dialog.style.display = 'flex';
            this.load();
            return this;
        },

        /** 关闭个人资料编辑弹窗 */
        close() {
            const dialog = document.getElementById('p0-profile-dialog-ai');
            if (dialog) dialog.remove();
        },
    };

    // ============================
    // 4. 账户注销 UI
    // ============================
    const AccountCancellation = {
        async showDialog() {
            // 先检查状态
            let status;
            try {
                status = await apiRequest('/api/account/deletion-status');
            } catch (e) {
                showToast('无法获取账户状态: ' + e.message, 'error');
                return;
            }

            if (status.is_deleted) {
                if (status.deletion_type === 'soft' && status.can_restore) {
                    this.showRestoreDialog(status);
                } else {
                    showToast(`账户已${status.deletion_type === 'soft' ? '注销' : '永久注销'},无法再次操作`, 'error');
                }
                return;
            }

            this.showCancelDialog();
        },

        showCancelDialog() {
            const old = document.getElementById('p0-cancel-dialog');
            if (old) old.remove();

            const html = `
                <div id="p0-cancel-dialog" style="position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;display:flex;align-items:center;justify-content:center;">
                    <div style="background:#fff;border-radius:12px;padding:24px;width:420px;max-width:90%;box-shadow:0 10px 40px rgba(0,0,0,.2);max-height:90vh;overflow:auto;">
                        <h3 style="margin:0 0 12px;font-size:18px;color:#dc2626;">⚠️ 注销账户</h3>
                        <div style="background:#fef3c7;border-left:3px solid #f59e0b;padding:10px 12px;border-radius:4px;margin-bottom:16px;font-size:13px;color:#78350f;">
                            <strong>注销协议:</strong><br>
                            1. 软注销后账户将进入30天保留期<br>
                            2. 期间您可以随时登录恢复账户<br>
                            3. 30天后账户将被永久删除,数据不可恢复<br>
                            4. 注销不会影响您的法律义务和已发生的数据
                        </div>
                        <div class="profile-field">
                            <label>注销原因(可选)</label>
                            <textarea id="p0-cancel-reason" rows="2" placeholder="为什么注销?您的反馈对我们很重要" style="width:100%;padding:8px;border:1px solid #d1d5db;border-radius:6px;box-sizing:border-box;"></textarea>
                        </div>
                        <div class="profile-field" style="margin-top:12px;">
                            <label>登录密码 <span class="required">*</span></label>
                            <input id="p0-cancel-password" type="password" placeholder="请输入登录密码" style="width:100%;padding:8px;border:1px solid #d1d5db;border-radius:6px;box-sizing:border-box;" />
                        </div>
                        <div style="margin-top:12px;display:flex;align-items:center;gap:6px;">
                            <input id="p0-cancel-confirm" type="checkbox" />
                            <label for="p0-cancel-confirm" style="font-size:13px;color:#374151;cursor:pointer;">我已阅读并同意《注销协议》</label>
                        </div>
                        <div id="p0-cancel-error" style="color:#ef4444;font-size:12px;margin-top:8px;min-height:18px;"></div>
                        <div style="display:flex;gap:8px;margin-top:16px;">
                            <button id="p0-cancel-close" style="flex:1;padding:10px;background:#f3f4f6;color:#374151;border:none;border-radius:6px;cursor:pointer;">取消</button>
                            <button id="p0-cancel-submit" style="flex:1;padding:10px;background:#dc2626;color:#fff;border:none;border-radius:6px;cursor:pointer;">确认注销</button>
                        </div>
                    </div>
                </div>
            `;
            const div = document.createElement('div');
            div.innerHTML = html;
            document.body.appendChild(div.firstElementChild);

            document.getElementById('p0-cancel-close').onclick = () => {
                document.getElementById('p0-cancel-dialog').remove();
            };

            document.getElementById('p0-cancel-submit').onclick = async () => {
                const password = document.getElementById('p0-cancel-password').value;
                const reason = document.getElementById('p0-cancel-reason').value.trim();
                const confirm = document.getElementById('p0-cancel-confirm').checked;
                const errEl = document.getElementById('p0-cancel-error');

                if (!password) { errEl.textContent = '请输入密码'; return; }
                if (!confirm) { errEl.textContent = '请阅读并同意注销协议'; return; }

                try {
                    const result = await apiRequest('/api/account/cancel', {
                        method: 'POST',
                        body: JSON.stringify({ password, reason, confirm: true }),
                    });
                    alert(`账户已注销!\n\n${result.message}\n\n您有 ${result.restore_days} 天时间恢复账户。\n恢复截止时间: ${result.restore_deadline}`);
                    document.getElementById('p0-cancel-dialog').remove();
                    // 跳转到登录页
                    setTimeout(() => {
                        localStorage.removeItem('rag-auth-token');
                        localStorage.removeItem('auth_token');
                        location.reload();
                    }, 1500);
                } catch (e) {
                    errEl.textContent = e.message || '注销失败';
                }
            };
        },

        showRestoreDialog(status) {
            const old = document.getElementById('p0-restore-dialog');
            if (old) old.remove();

            const html = `
                <div id="p0-restore-dialog" style="position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;display:flex;align-items:center;justify-content:center;">
                    <div style="background:#fff;border-radius:12px;padding:24px;width:380px;max-width:90%;">
                        <h3 style="margin:0 0 12px;font-size:18px;color:#10b981;">🔄 恢复账户</h3>
                        <p style="margin:0 0 16px;color:#6b7280;font-size:14px;line-height:1.5;">
                            您的账户已注销,还有 <strong style="color:#ef4444;">${status.days_remaining}</strong> 天恢复期限。<br>
                            恢复截止时间: <strong>${new Date(status.restore_deadline).toLocaleString('zh-CN')}</strong>
                        </p>
                        <div class="profile-field">
                            <label>登录密码</label>
                            <input id="p0-restore-password" type="password" placeholder="请输入登录密码" style="width:100%;padding:8px;border:1px solid #d1d5db;border-radius:6px;box-sizing:border-box;" />
                        </div>
                        <div id="p0-restore-error" style="color:#ef4444;font-size:12px;margin-top:6px;min-height:18px;"></div>
                        <div style="display:flex;gap:8px;margin-top:16px;">
                            <button id="p0-restore-cancel" style="flex:1;padding:10px;background:#f3f4f6;color:#374151;border:none;border-radius:6px;cursor:pointer;">取消</button>
                            <button id="p0-restore-submit" style="flex:1;padding:10px;background:#10b981;color:#fff;border:none;border-radius:6px;cursor:pointer;">立即恢复</button>
                        </div>
                    </div>
                </div>
            `;
            const div = document.createElement('div');
            div.innerHTML = html;
            document.body.appendChild(div.firstElementChild);

            document.getElementById('p0-restore-cancel').onclick = () => {
                document.getElementById('p0-restore-dialog').remove();
            };

            document.getElementById('p0-restore-submit').onclick = async () => {
                const password = document.getElementById('p0-restore-password').value;
                const errEl = document.getElementById('p0-restore-error');
                if (!password) { errEl.textContent = '请输入密码'; return; }

                try {
                    await apiRequest('/api/account/restore', {
                        method: 'POST',
                        body: JSON.stringify({ password }),
                    });
                    showToast('账户已恢复,欢迎回来!', 'success');
                    document.getElementById('p0-restore-dialog').remove();
                    setTimeout(() => location.reload(), 1500);
                } catch (e) {
                    errEl.textContent = e.message || '恢复失败';
                }
            };
        },
    };

    // ============================
    // 暴露到全局
    // ============================
    window.P0Modules = {
        PhoneBindingDialog,
        FriendRequestsModule,
        ProfileForm,
        AccountCancellation,
    };

    // AI可调用函数注册表（供WebSocket消息路由调用）
    window.__aiCallableFunctions = window.__aiCallableFunctions || {};
    window.__aiCallableFunctions['openProfileForm'] = {
        name: 'openProfileForm',
        description: '打开个人资料编辑弹窗，用户可查看和修改个人资料',
        execute: function(params) {
            if (window.P0Modules && window.P0Modules.ProfileForm) {
                window.P0Modules.ProfileForm.show();
                return { success: true, message: '个人资料弹窗已打开' };
            }
            return { success: false, message: '个人资料模块未加载' };
        }
    };
    window.__aiCallableFunctions['updateProfileField'] = {
        name: 'updateProfileField',
        description: '更新个人资料的指定字段值',
        parameters: {
            field: { type: 'string', description: '字段名: nickname, real_name, gender, city, bio, target_country, target_level, language_score, education' },
            value: { type: 'string', description: '字段值' }
        },
        execute: function(params) {
            if (window.P0Modules && window.P0Modules.ProfileForm) {
                window.P0Modules.ProfileForm.updateField(params.field, params.value);
                return { success: true, message: '字段 ' + params.field + ' 已更新' };
            }
            return { success: false, message: '个人资料模块未加载' };
        }
    };

    console.log('[P0模块] 已加载', { ROLE, API_BASE });
})();
