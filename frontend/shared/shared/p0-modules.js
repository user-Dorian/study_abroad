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
    // P0-001 修复：改为函数式获取 ROLE，避免脚本加载顺序问题
    function getRole() { return window.ROLE || 'client'; }
    // 保留 ROLE 变量（向后兼容），但实际渲染使用 getRole()
    const ROLE = getRole();

    // ============================
    // 工具函数
    // ============================
    async function apiRequest(url, options = {}) {
        const token = localStorage.getItem('rag-auth-token') 
            || localStorage.getItem('consultant-auth-token')
            || localStorage.getItem('auth_token') 
            || '';
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
            console.log('[ProfileForm] load() 方法被调用');
            try {
                console.log('[ProfileForm] 开始请求API数据...');
                const [profile, completeness] = await Promise.all([
                    apiRequest('/api/profile/me'),
                    apiRequest('/api/profile/completeness'),
                ]);
                console.log('[ProfileForm] API返回成功:', { profile, completeness });
                this.state.profile = profile;
                this.state.completeness = completeness;
                this.state.formData = { ...profile };
                this.state.isDirty = false;
                console.log('[ProfileForm] 状态已更新,准备渲染...');
                this.render();
                console.log('[ProfileForm] 渲染完成');
            } catch (e) {
                console.error('[ProfileForm] 加载失败:', e);
                console.error('[ProfileForm] 错误详情:', {
                    message: e.message,
                    stack: e.stack,
                    name: e.name
                });
                showToast('加载资料失败: ' + e.message, 'error');
                // 渲染错误状态
                this.renderError(e.message);
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

        renderError(errorMessage) {
            const container = document.getElementById('profile-form-container');
            if (!container) {
                console.error('[ProfileForm] 未找到容器元素 #profile-form-container');
                return;
            }
            console.log('[ProfileForm] 渲染错误状态');
            container.innerHTML = `
                <div style="padding:20px;text-align:center;background:#fef2f2;border:1px solid #fecaca;border-radius:8px;margin:10px 0;">
                    <div style="color:#dc2626;font-size:16px;font-weight:bold;margin-bottom:10px;">⚠️ 加载失败</div>
                    <div style="color:#7f1d1d;font-size:14px;margin-bottom:15px;">${escapeHtml(errorMessage)}</div>
                    <button onclick="window.P0Modules.ProfileForm.load()" style="padding:8px 16px;background:#3b82f6;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:14px;">
                        重新加载
                    </button>
                </div>
            `;
        },

        render() {
            console.log('[ProfileForm] render() 方法被调用');
            const container = document.getElementById('profile-form-container');
            if (!container) {
                console.error('[ProfileForm] 未找到容器元素 #profile-form-container');
                return;
            }
            console.log('[ProfileForm] 找到容器,开始渲染表单...');
            const p = this.state.formData;
            const c = this.state.completeness;
            console.log('[ProfileForm] 渲染数据:', { formData: p, completeness: c });

            container.innerHTML = `
                <div class="profile-completeness">
                    <div class="pc-bar"><div class="pc-fill" style="width:${c.completeness || 0}%"></div></div>
                    <div class="pc-text">资料完整度: <strong>${c.completeness || 0}%</strong>
                        ${c.missing_required && c.missing_required.length > 0
                            ? `<span style="color:#ef4444;margin-left:8px;">缺失: ${c.missing_required.join(', ')}</span>`
                            : ''}
                    </div>
                </div>

                <!-- P0-016 修复：头像上传 -->
                <div class="profile-section">
                    <h4>头像</h4>
                    <div class="profile-field" style="display:flex;align-items:center;gap:16px;">
                        <div id="profile-avatar-preview" style="width:72px;height:72px;border-radius:50%;background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;display:flex;align-items:center;justify-content:center;font-size:32px;font-weight:600;overflow:hidden;flex-shrink:0;">
                            ${p.avatar_url ? `<img src="${escapeHtml(p.avatar_url)}" style="width:100%;height:100%;object-fit:cover;" />` : escapeHtml((p.nickname || p.real_name || '?')[0])}
                        </div>
                        <div style="flex:1;">
                            <input type="file" id="profile-avatar-input" accept="image/*" style="display:none;" />
                            <button type="button" id="profile-avatar-btn" style="padding:8px 16px;background:#3b82f6;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:14px;">📷 上传头像</button>
                            <button type="button" id="profile-avatar-url-btn" style="padding:8px 16px;background:#f3f4f6;color:#374151;border:none;border-radius:6px;cursor:pointer;font-size:14px;margin-left:6px;">🔗 使用URL</button>
                            <div style="color:#6b7280;font-size:12px;margin-top:6px;">支持 jpg/png/webp，最大 2MB</div>
                        </div>
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
                                   placeholder="${p.phone_bound ? '已绑定' : '未绑定'}" maxlength="11" style="flex:1;${p.phone_bound ? 'background:#f5f5f5;color:#999;' : ''}"
                                   ${p.phone_bound ? 'disabled' : ''} />
                            <button id="profile-phone-btn"
                                    style="padding:8px 16px;background:${p.phone_bound ? '#f59e0b' : '#10b981'};color:#fff;border:none;border-radius:6px;cursor:pointer;">
                                ${p.phone_bound ? '解绑/换绑' : '绑定'}
                            </button>
                        </div>
                    </div>
                </div>

                ${getRole() === 'client' ? `
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
                    <h4>规划师简介 <span class="required">*</span></h4>
                    <div class="profile-field">
                        <label>个人介绍</label>
                        <textarea data-field="consultant_bio" rows="3" placeholder="请介绍您的专业背景和服务特点">${escapeHtml(p.consultant_bio || '')}</textarea>
                    </div>
                    <div class="profile-field">
                        <label>专长领域 <span class="required">*</span>(逗号分隔)</label>
                        <input type="text" data-field="expertise_areas_str"
                               value="${escapeHtml((p.expertise_areas || []).join(', '))}"
                               placeholder="如:美国留学, 奖学金申请, STEM专业" />
                    </div>
                </div>
                <div class="profile-section">
                    <h4>专业资历</h4>
                    <div class="profile-field">
                        <label>从业年限</label>
                        <input type="text" data-field="experience_years_consultant"
                               value="${escapeHtml(p.experience_years_consultant || '')}"
                               placeholder="如: 5年" />
                    </div>
                    <div class="profile-field">
                        <label>成功案例数</label>
                        <input type="number" data-field="success_cases"
                               value="${p.success_cases || 0}" min="0" />
                    </div>
                    <div class="profile-field">
                        <label>认证状态</label>
                        <select data-field="verified">
                            <option value="false" ${p.verified === false || p.verified === 'false' ? 'selected' : ''}>未认证</option>
                            <option value="true" ${p.verified === true || p.verified === 'true' ? 'selected' : ''}>已认证</option>
                        </select>
                    </div>
                </div>
                <div class="profile-section">
                    <h4>服务信息</h4>
                    <div class="profile-field">
                        <label>服务价格</label>
                        <input type="text" data-field="service_price"
                               value="${escapeHtml(p.service_price || '')}"
                               placeholder="如: 500元/小时 或 面议" />
                    </div>
                    <div class="profile-field">
                        <label>个人网站/主页</label>
                        <input type="text" data-field="website"
                               value="${escapeHtml(p.website || '')}"
                               placeholder="https://..." />
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
                    if (p.phone_bound) {
                        // 已绑定：弹出确认框
                        if (!confirm('确定要解绑当前手机号吗？解绑后将无法使用部分社交功能。')) {
                            return;
                        }
                        // 解绑操作
                        try {
                            await apiRequest('/api/profile/me/phone', { method: 'DELETE' });
                            showToast('手机号已解绑', 'warning');
                            this.load(); // 重新加载
                        } catch (e) {
                            showToast('解绑失败: ' + e.message, 'error');
                        }
                    } else {
                        // 未绑定：执行绑定逻辑
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
                            showToast('手机号绑定成功!', 'success');
                            this.load();
                        } catch (e) {
                            showToast('绑定失败: ' + e.message, 'error');
                        }
                    }
                };
            }

            // 保存按钮
            const saveBtn = document.getElementById('profile-save-btn');
            if (saveBtn) saveBtn.onclick = () => this.save();
            this.renderSaveButton();

            // P0-016 修复：头像上传按钮事件
            const avatarInput = document.getElementById('profile-avatar-input');
            const avatarBtn = document.getElementById('profile-avatar-btn');
            const avatarUrlBtn = document.getElementById('profile-avatar-url-btn');
            if (avatarBtn && avatarInput) {
                avatarBtn.onclick = () => avatarInput.click();
                avatarInput.onchange = (e) => {
                    const file = e.target.files && e.target.files[0];
                    if (!file) return;
                    if (file.size > 2 * 1024 * 1024) {
                        showToast('图片大小不能超过 2MB', 'error');
                        return;
                    }
                    if (!file.type.startsWith('image/')) {
                        showToast('请选择图片文件', 'error');
                        return;
                    }
                    // 使用 FileReader 预览
                    const reader = new FileReader();
                    reader.onload = (evt) => {
                        const dataUrl = evt.target.result;
                        // 直接将头像作为 dataURL 提交（无需后端上传接口）
                        this.updateField('avatar_url', dataUrl);
                        const preview = document.getElementById('profile-avatar-preview');
                        if (preview) {
                            preview.innerHTML = `<img src="${dataUrl}" style="width:100%;height:100%;object-fit:cover;" />`;
                        }
                        showToast('头像已选择，点击"保存修改"生效', 'success');
                    };
                    reader.readAsDataURL(file);
                };
            }
            if (avatarUrlBtn) {
                avatarUrlBtn.onclick = () => {
                    const url = prompt('请输入头像图片URL:', p.avatar_url || '');
                    if (url === null) return;
                    this.updateField('avatar_url', url.trim());
                    const preview = document.getElementById('profile-avatar-preview');
                    if (preview) {
                        if (url.trim()) {
                            preview.innerHTML = `<img src="${escapeHtml(url.trim())}" style="width:100%;height:100%;object-fit:cover;" onerror="this.parentNode.innerHTML='${escapeHtml((p.nickname || '?')[0])}'" />`;
                        } else {
                            preview.innerHTML = escapeHtml((p.nickname || p.real_name || '?')[0]);
                        }
                    }
                };
            }
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
    // 4. 设置模块（SettingsModule）
    // ============================
    const SettingsModule = {
        state: {
            settings: {},
            loading: false,
            saving: false,
            activeTab: 'notification',
        },

        // 默认设置值
        defaultSettings: {
            // 通知设置
            notification: {
                message_notify: true,
                sound_notify: true,
                desktop_notify: false,
            },
            // 隐私设置
            privacy: {
                show_online_status: true,
                show_read_receipt: true,
                allow_add_friend: true,
            },
            // 偏好设置
            preference: {
                theme: 'light',
                font_size: 'medium',
                language: 'zh-CN',
            },
            // 安全设置
            security: {
                two_factor_auth: false,
                login_notify: true,
            },
            // 数据管理
            data: {
                auto_clear_cache: false,
                cache_size_limit: 100,
                export_format: 'json',
            }
        },

        async load() {
            console.log('[SettingsModule] load() 方法被调用');
            this.state.loading = true;
            // P0-010 修复：先从 localStorage 读取本地缓存，立即展示，避免空白闪烁
            try {
                const cached = localStorage.getItem('user_settings');
                if (cached) {
                    const parsed = JSON.parse(cached);
                    this.state.settings = { ...this.defaultSettings, ...parsed };
                    this.render();
                    console.log('[SettingsModule] 从 localStorage 加载缓存设置');
                }
            } catch (e) {
                console.warn('[SettingsModule] localStorage 解析失败:', e);
            }
            try {
                const settings = await apiRequest('/api/settings/me');
                console.log('[SettingsModule] API返回成功:', settings);
                this.state.settings = { ...this.defaultSettings, ...settings };
                // 同步到 localStorage
                try {
                    localStorage.setItem('user_settings', JSON.stringify(this.state.settings));
                } catch (e) { /* ignore */ }
                this.render();
            } catch (e) {
                console.error('[SettingsModule] 加载失败:', e);
                if (!this.state.settings || Object.keys(this.state.settings).length === 0) {
                    this.state.settings = { ...this.defaultSettings };
                    this.render();
                }
            } finally {
                this.state.loading = false;
            }
        },

        async save(category, settings) {
            console.log('[SettingsModule] save() 方法被调用', category, settings);
            this.state.saving = true;
            try {
                await apiRequest('/api/settings/me', {
                    method: 'PUT',
                    body: JSON.stringify({ category, settings }),
                });
                console.log('[SettingsModule] 保存成功');
                this.state.settings[category] = { ...this.state.settings[category], ...settings };
                // 同时保存到localStorage作为备份
                localStorage.setItem('user_settings', JSON.stringify(this.state.settings));
                showToast('设置已保存', 'success');
                return true;
            } catch (e) {
                console.error('[SettingsModule] 保存失败:', e);
                showToast('保存失败: ' + e.message, 'error');
                return false;
            } finally {
                this.state.saving = false;
            }
        },

        async show() {
            // 移除旧弹窗
            const old = document.getElementById('settings-module-dialog');
            if (old) old.remove();

            const html = `
                <div id="settings-module-dialog" style="position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;display:flex;align-items:center;justify-content:center;">
                    <div style="background:#fff;border-radius:12px;padding:0;width:720px;max-width:95%;max-height:90vh;display:flex;flex-direction:column;box-shadow:0 10px 40px rgba(0,0,0,.2);">
                        <div style="padding:20px 24px;border-bottom:1px solid #e5e7eb;display:flex;justify-content:space-between;align-items:center;">
                            <h3 style="margin:0;font-size:20px;color:#1f2937;">⚙️ 设置</h3>
                            <button id="settings-close-btn" style="background:none;border:none;font-size:24px;color:#6b7280;cursor:pointer;padding:0;width:32px;height:32px;display:flex;align-items:center;justify-content:center;border-radius:4px;">×</button>
                        </div>
                        <div style="display:flex;flex:1;overflow:hidden;">
                            <div id="settings-sidebar" style="width:200px;background:#f9fafb;border-right:1px solid #e5e7eb;padding:16px 0;">
                                <button class="settings-tab-btn active" data-tab="notification">通知设置</button>
                                <button class="settings-tab-btn" data-tab="privacy">隐私设置</button>
                                <button class="settings-tab-btn" data-tab="preference">偏好设置</button>
                                <button class="settings-tab-btn" data-tab="security">安全设置</button>
                                <button class="settings-tab-btn" data-tab="data">数据管理</button>
                            </div>
                            <div id="settings-content" style="flex:1;padding:24px;overflow-y:auto;">
                                <div style="text-align:center;padding:40px;color:#9ca3af;">加载中...</div>
                            </div>
                        </div>
                    </div>
                </div>
            `;

            const div = document.createElement('div');
            div.innerHTML = html;
            document.body.appendChild(div.firstElementChild);

            // 绑定关闭按钮
            document.getElementById('settings-close-btn').onclick = () => {
                document.getElementById('settings-module-dialog').remove();
            };

            // 绑定标签切换
            document.querySelectorAll('.settings-tab-btn').forEach(btn => {
                btn.onclick = () => {
                    document.querySelectorAll('.settings-tab-btn').forEach(b => b.classList.remove('active'));
                    btn.classList.add('active');
                    this.state.activeTab = btn.dataset.tab;
                    this.renderTabContent();
                };
            });

            // 加载设置
            await this.load();
        },

        renderTabContent() {
            const container = document.getElementById('settings-content');
            if (!container) return;

            const tab = this.state.activeTab;
            const settings = this.state.settings[tab] || {};

            let html = '';
            switch (tab) {
                case 'notification':
                    html = this.renderNotificationSettings(settings);
                    break;
                case 'privacy':
                    html = this.renderPrivacySettings(settings);
                    break;
                case 'preference':
                    html = this.renderPreferenceSettings(settings);
                    break;
                case 'security':
                    html = this.renderSecuritySettings(settings);
                    break;
                case 'data':
                    html = this.renderDataSettings(settings);
                    break;
            }
            container.innerHTML = html;
            this.bindTabEvents(tab);
        },

        renderNotificationSettings(s) {
            return `
                <div class="settings-section">
                    <h4 style="margin:0 0 16px;font-size:16px;color:#1f2937;">消息提醒</h4>
                    <div class="settings-item">
                        <div class="settings-item-info">
                            <div class="settings-item-title">消息通知</div>
                            <div class="settings-item-desc">接收新消息时显示通知提醒</div>
                        </div>
                        <label class="settings-switch">
                            <input type="checkbox" data-setting="message_notify" ${s.message_notify ? 'checked' : ''} />
                            <span class="slider"></span>
                        </label>
                    </div>
                    <div class="settings-item">
                        <div class="settings-item-info">
                            <div class="settings-item-title">声音提醒</div>
                            <div class="settings-item-desc">收到新消息时播放提示音</div>
                        </div>
                        <label class="settings-switch">
                            <input type="checkbox" data-setting="sound_notify" ${s.sound_notify ? 'checked' : ''} />
                            <span class="slider"></span>
                        </label>
                    </div>
                    <div class="settings-item">
                        <div class="settings-item-info">
                            <div class="settings-item-title">桌面通知</div>
                            <div class="settings-item-desc">使用浏览器桌面通知显示消息</div>
                        </div>
                        <label class="settings-switch">
                            <input type="checkbox" data-setting="desktop_notify" ${s.desktop_notify ? 'checked' : ''} />
                            <span class="slider"></span>
                        </label>
                    </div>
                </div>
            `;
        },

        renderPrivacySettings(s) {
            return `
                <div class="settings-section">
                    <h4 style="margin:0 0 16px;font-size:16px;color:#1f2937;">在线状态</h4>
                    <div class="settings-item">
                        <div class="settings-item-info">
                            <div class="settings-item-title">显示在线状态</div>
                            <div class="settings-item-desc">允许其他用户查看您的在线状态</div>
                        </div>
                        <label class="settings-switch">
                            <input type="checkbox" data-setting="show_online_status" ${s.show_online_status ? 'checked' : ''} />
                            <span class="slider"></span>
                        </label>
                    </div>
                    <div class="settings-item">
                        <div class="settings-item-info">
                            <div class="settings-item-title">已读回执</div>
                            <div class="settings-item-desc">发送消息已读状态给对方</div>
                        </div>
                        <label class="settings-switch">
                            <input type="checkbox" data-setting="show_read_receipt" ${s.show_read_receipt ? 'checked' : ''} />
                            <span class="slider"></span>
                        </label>
                    </div>
                    <div class="settings-item">
                        <div class="settings-item-info">
                            <div class="settings-item-title">允许添加好友</div>
                            <div class="settings-item-desc">允许其他用户发送好友申请</div>
                        </div>
                        <label class="settings-switch">
                            <input type="checkbox" data-setting="allow_add_friend" ${s.allow_add_friend ? 'checked' : ''} />
                            <span class="slider"></span>
                        </label>
                    </div>
                </div>
            `;
        },

        renderPreferenceSettings(s) {
            return `
                <div class="settings-section">
                    <h4 style="margin:0 0 16px;font-size:16px;color:#1f2937;">外观设置</h4>
                    <div class="settings-item">
                        <div class="settings-item-info">
                            <div class="settings-item-title">主题模式</div>
                            <div class="settings-item-desc">选择浅色或深色主题</div>
                        </div>
                        <select data-setting="theme" class="settings-select">
                            <option value="light" ${s.theme === 'light' ? 'selected' : ''}>浅色模式</option>
                            <option value="dark" ${s.theme === 'dark' ? 'selected' : ''}>深色模式</option>
                            <option value="auto" ${s.theme === 'auto' ? 'selected' : ''}>跟随系统</option>
                        </select>
                    </div>
                    <div class="settings-item">
                        <div class="settings-item-info">
                            <div class="settings-item-title">字体大小</div>
                            <div class="settings-item-desc">调整界面文字显示大小</div>
                        </div>
                        <select data-setting="font_size" class="settings-select">
                            <option value="small" ${s.font_size === 'small' ? 'selected' : ''}>小号</option>
                            <option value="medium" ${s.font_size === 'medium' ? 'selected' : ''}>中号</option>
                            <option value="large" ${s.font_size === 'large' ? 'selected' : ''}>大号</option>
                        </select>
                    </div>
                    <div class="settings-item">
                        <div class="settings-item-info">
                            <div class="settings-item-title">界面语言</div>
                            <div class="settings-item-desc">选择界面显示语言</div>
                        </div>
                        <select data-setting="language" class="settings-select">
                            <option value="zh-CN" ${s.language === 'zh-CN' ? 'selected' : ''}>简体中文</option>
                            <option value="zh-TW" ${s.language === 'zh-TW' ? 'selected' : ''}>繁體中文</option>
                            <option value="en" ${s.language === 'en' ? 'selected' : ''}>English</option>
                        </select>
                    </div>
                </div>
            `;
        },

        renderSecuritySettings(s) {
            return `
                <div class="settings-section">
                    <h4 style="margin:0 0 16px;font-size:16px;color:#1f2937;">账号安全</h4>
                    <div class="settings-item">
                        <div class="settings-item-info">
                            <div class="settings-item-title">修改密码</div>
                            <div class="settings-item-desc">定期修改密码以提高账号安全性</div>
                        </div>
                        <button id="change-password-btn" class="settings-btn">修改密码</button>
                    </div>
                    <div class="settings-item">
                        <div class="settings-item-info">
                            <div class="settings-item-title">两步验证</div>
                            <div class="settings-item-desc">启用额外的安全验证层</div>
                        </div>
                        <label class="settings-switch">
                            <input type="checkbox" data-setting="two_factor_auth" ${s.two_factor_auth ? 'checked' : ''} />
                            <span class="slider"></span>
                        </label>
                    </div>
                    <div class="settings-item">
                        <div class="settings-item-info">
                            <div class="settings-item-title">登录提醒</div>
                            <div class="settings-item-desc">新设备登录时发送通知</div>
                        </div>
                        <label class="settings-switch">
                            <input type="checkbox" data-setting="login_notify" ${s.login_notify ? 'checked' : ''} />
                            <span class="slider"></span>
                        </label>
                    </div>
                    <div class="settings-item">
                        <div class="settings-item-info">
                            <div class="settings-item-title">登录历史</div>
                            <div class="settings-item-desc">查看最近的登录记录</div>
                        </div>
                        <button id="view-login-history-btn" class="settings-btn">查看记录</button>
                    </div>
                </div>
            `;
        },

        renderDataSettings(s) {
            return `
                <div class="settings-section">
                    <h4 style="margin:0 0 16px;font-size:16px;color:#1f2937;">数据管理</h4>
                    <div class="settings-item">
                        <div class="settings-item-info">
                            <div class="settings-item-title">自动清理缓存</div>
                            <div class="settings-item-desc">自动清理超过限制的缓存数据</div>
                        </div>
                        <label class="settings-switch">
                            <input type="checkbox" data-setting="auto_clear_cache" ${s.auto_clear_cache ? 'checked' : ''} />
                            <span class="slider"></span>
                        </label>
                    </div>
                    <div class="settings-item">
                        <div class="settings-item-info">
                            <div class="settings-item-title">缓存大小限制</div>
                            <div class="settings-item-desc">设置缓存数据最大容量（MB）</div>
                        </div>
                        <input type="number" data-setting="cache_size_limit" value="${s.cache_size_limit || 100}" min="50" max="500" class="settings-input" style="width:100px;padding:8px;" />
                    </div>
                    <div class="settings-item">
                        <div class="settings-item-info">
                            <div class="settings-item-title">导出格式</div>
                            <div class="settings-item-desc">选择数据导出的文件格式</div>
                        </div>
                        <select data-setting="export_format" class="settings-select">
                            <option value="json" ${s.export_format === 'json' ? 'selected' : ''}>JSON</option>
                            <option value="csv" ${s.export_format === 'csv' ? 'selected' : ''}>CSV</option>
                        </select>
                    </div>
                    <div class="settings-item">
                        <div class="settings-item-info">
                            <div class="settings-item-title">清除缓存</div>
                            <div class="settings-item-desc">立即清除所有本地缓存数据</div>
                        </div>
                        <button id="clear-cache-btn" class="settings-btn" style="background:#ef4444;">清除缓存</button>
                    </div>
                    <div class="settings-item">
                        <div class="settings-item-info">
                            <div class="settings-item-title">导出个人数据</div>
                            <div class="settings-item-desc">下载您的所有个人数据</div>
                        </div>
                        <button id="export-data-btn" class="settings-btn">导出数据</button>
                    </div>
                </div>
            `;
        },

        bindTabEvents(tab) {
            const container = document.getElementById('settings-content');
            if (!container) return;

            // 绑定所有开关和输入框的change事件
            container.querySelectorAll('[data-setting]').forEach(el => {
                el.onchange = async (e) => {
                    const key = e.target.dataset.setting;
                    let value;
                    if (e.target.type === 'checkbox') {
                        value = e.target.checked;
                    } else if (e.target.type === 'number') {
                        value = parseInt(e.target.value);
                    } else {
                        value = e.target.value;
                    }
                    const newSettings = { [key]: value };
                    await this.save(tab, newSettings);
                };
            });

            // 特殊按钮事件
            if (tab === 'security') {
                const changePwdBtn = document.getElementById('change-password-btn');
                if (changePwdBtn) {
                    changePwdBtn.onclick = () => this.showChangePasswordDialog();
                }
                const viewHistoryBtn = document.getElementById('view-login-history-btn');
                if (viewHistoryBtn) {
                    viewHistoryBtn.onclick = () => this.showLoginHistory();
                }
            }

            if (tab === 'data') {
                const clearCacheBtn = document.getElementById('clear-cache-btn');
                if (clearCacheBtn) {
                    clearCacheBtn.onclick = () => this.clearCache();
                }
                const exportDataBtn = document.getElementById('export-data-btn');
                if (exportDataBtn) {
                    exportDataBtn.onclick = () => this.exportData();
                }
            }
        },

        render() {
            this.renderTabContent();
        },

        async showChangePasswordDialog() {
            const html = `
                <div id="change-password-dialog" style="position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:10000;display:flex;align-items:center;justify-content:center;">
                    <div style="background:#fff;border-radius:12px;padding:24px;width:400px;max-width:90%;">
                        <h3 style="margin:0 0 16px;font-size:18px;color:#1f2937;">修改密码</h3>
                        <div class="profile-field">
                            <label>当前密码</label>
                            <input type="password" id="old-password" style="width:100%;padding:8px;border:1px solid #d1d5db;border-radius:6px;box-sizing:border-box;" />
                        </div>
                        <div class="profile-field">
                            <label>新密码</label>
                            <input type="password" id="new-password" style="width:100%;padding:8px;border:1px solid #d1d5db;border-radius:6px;box-sizing:border-box;" />
                        </div>
                        <div class="profile-field">
                            <label>确认新密码</label>
                            <input type="password" id="confirm-password" style="width:100%;padding:8px;border:1px solid #d1d5db;border-radius:6px;box-sizing:border-box;" />
                        </div>
                        <div id="change-password-error" style="color:#ef4444;font-size:12px;margin-top:6px;min-height:18px;"></div>
                        <div style="display:flex;gap:8px;margin-top:16px;">
                            <button id="cancel-change-password" style="flex:1;padding:10px;background:#f3f4f6;color:#374151;border:none;border-radius:6px;cursor:pointer;">取消</button>
                            <button id="submit-change-password" style="flex:1;padding:10px;background:#3b82f6;color:#fff;border:none;border-radius:6px;cursor:pointer;">确认修改</button>
                        </div>
                    </div>
                </div>
            `;

            const div = document.createElement('div');
            div.innerHTML = html;
            document.body.appendChild(div.firstElementChild);

            document.getElementById('cancel-change-password').onclick = () => {
                document.getElementById('change-password-dialog').remove();
            };

            document.getElementById('submit-change-password').onclick = async () => {
                const oldPwd = document.getElementById('old-password').value;
                const newPwd = document.getElementById('new-password').value;
                const confirmPwd = document.getElementById('confirm-password').value;
                const errEl = document.getElementById('change-password-error');

                if (!oldPwd || !newPwd || !confirmPwd) {
                    errEl.textContent = '请填写所有字段';
                    return;
                }
                if (newPwd !== confirmPwd) {
                    errEl.textContent = '两次输入的新密码不一致';
                    return;
                }
                if (newPwd.length < 6) {
                    errEl.textContent = '新密码长度至少6位';
                    return;
                }

                try {
                    await apiRequest('/api/settings/change-password', {
                        method: 'POST',
                        body: JSON.stringify({ old_password: oldPwd, new_password: newPwd }),
                    });
                    showToast('密码修改成功，请重新登录', 'success');
                    document.getElementById('change-password-dialog').remove();
                    setTimeout(() => {
                        localStorage.clear();
                        window.location.href = '/login.html';
                    }, 1500);
                } catch (e) {
                    errEl.textContent = e.message || '修改失败';
                }
            };
        },

        async showLoginHistory() {
            try {
                showToast('加载登录历史...', 'info');
                const history = await apiRequest('/api/settings/login-history');
                const html = `
                    <div id="login-history-dialog" style="position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:10000;display:flex;align-items:center;justify-content:center;">
                        <div style="background:#fff;border-radius:12px;padding:24px;width:500px;max-width:90%;max-height:80vh;overflow-y:auto;">
                            <h3 style="margin:0 0 16px;font-size:18px;color:#1f2937;">登录历史</h3>
                            <div style="max-height:400px;overflow-y:auto;">
                                ${(history && history.length > 0) ? history.map(item => `
                                    <div style="padding:12px;border-bottom:1px solid #e5e7eb;">
                                        <div style="font-weight:500;color:#1f2937;">${escapeHtml(item.ip || '未知IP')}</div>
                                        <div style="font-size:12px;color:#6b7280;margin-top:4px;">
                                            ${escapeHtml(item.device || '未知设备')} · ${new Date(item.timestamp).toLocaleString('zh-CN')}
                                        </div>
                                    </div>
                                `).join('') : '<div style="text-align:center;color:#9ca3af;padding:20px;">暂无登录记录</div>'}
                            </div>
                            <div style="margin-top:16px;text-align:right;">
                                <button id="close-login-history" style="padding:8px 16px;background:#3b82f6;color:#fff;border:none;border-radius:6px;cursor:pointer;">关闭</button>
                            </div>
                        </div>
                    </div>
                `;

                const div = document.createElement('div');
                div.innerHTML = html;
                document.body.appendChild(div.firstElementChild);

                document.getElementById('close-login-history').onclick = () => {
                    document.getElementById('login-history-dialog').remove();
                };
            } catch (e) {
                showToast('获取登录历史失败: ' + e.message, 'error');
            }
        },

        async clearCache() {
            if (!confirm('确定要清除所有本地缓存吗？这将清除本地存储的所有数据。')) return;

            try {
                localStorage.clear();
                sessionStorage.clear();
                showToast('缓存已清除', 'success');
            } catch (e) {
                showToast('清除失败: ' + e.message, 'error');
            }
        },

        async exportData() {
            if (!confirm('确定要导出您的个人数据吗？')) return;

            try {
                showToast('正在准备数据...', 'info');
                const response = await fetch(`${API_BASE}/api/settings/export-data`, {
                    method: 'GET',
                    headers: {
                        'Authorization': `Bearer ${localStorage.getItem('rag-auth-token') || localStorage.getItem('auth_token') || ''}`,
                    },
                });

                if (!response.ok) {
                    throw new Error('导出失败');
                }

                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `personal_data_${new Date().toISOString().split('T')[0]}.json`;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                document.body.removeChild(a);
                showToast('数据导出成功', 'success');
            } catch (e) {
                showToast('导出失败: ' + e.message, 'error');
            }
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
        SettingsModule,
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

    // 账户健康监控：定期检测账户状态，被注销时立即退出
    function _getAuthToken() {
        return localStorage.getItem('rag-auth-token') || localStorage.getItem('consultant-auth-token') || localStorage.getItem('auth_token') || '';
    }

    function _getLogoutUrl() {
        const token = _getAuthToken();
        // 检测使用哪个端的token
        if (localStorage.getItem('rag-auth-token')) return '/login.html';
        if (localStorage.getItem('consultant-auth-token')) return '/login.html';
        return '/login.html';
    }

    function _forceLogoutOnDeleted() {
        const msg = '您的账户已注销，即将退出登录。如有疑问请联系客服。';
        if (typeof showToast === 'function') {
            showToast(msg, 'error');
        } else {
            alert(msg);
        }
        // 清除所有认证信息
        localStorage.removeItem('rag-auth-token');
        localStorage.removeItem('rag-auth-user');
        localStorage.removeItem('consultant-auth-token');
        localStorage.removeItem('consultant-auth-user');
        localStorage.removeItem('auth_token');
        setTimeout(function() { window.location.href = _getLogoutUrl(); }, 2000);
    }

    /** 检测账户状态（被主动调用） */
    window.__checkAccountHealth = async function() {
        const token = _getAuthToken();
        if (!token) return { active: false, reason: '未登录' };
        try {
            const resp = await fetch('/api/account/deletion-status', {
                method: 'GET',
                headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' }
            });
            if (resp.status === 403) {
                // 账户已注销
                _forceLogoutOnDeleted();
                return { active: false, reason: '账户已注销' };
            }
            if (!resp.ok) return { active: true }; // 其他错误不阻断
            const data = await resp.json();
            if (data.is_deleted) {
                _forceLogoutOnDeleted();
                return { active: false, reason: '账户已注销' };
            }
            return { active: true };
        } catch (e) {
            console.warn('[账户健康] 检测失败:', e);
            return { active: true }; // 网络错误不阻断
        }
    };

    // 全局 API 响应拦截：捕获 403 账户已注销
    // 使用 try-catch 包裹，避免某些浏览器环境中 window.fetch 为只读属性导致的错误
    try {
        var _origFetch = window.fetch;
        if (typeof _origFetch === 'function') {
            Object.defineProperty(window, 'fetch', {
                value: function() {
                    var args = arguments;
                    return _origFetch.apply(window, args).then(function(response) {
                        if (response.status === 403) {
                            response.clone().json().then(function(data) {
                                if (data && data.detail && data.detail.indexOf('账户已注销') !== -1) {
                                    _forceLogoutOnDeleted();
                                }
                            }).catch(function() {});
                        }
                        return response;
                    }).catch(function(err) {
                        // 网络错误不处理
                        throw err;
                    });
                },
                writable: true,
                configurable: true
            });
        }
    } catch (e) {
        console.warn('[P0模块] 无法重写 window.fetch:', e.message);
    }

    // 定时健康检查（每60秒）
    var _healthInterval = setInterval(function() {
        window.__checkAccountHealth();
    }, 60000);

    // 页面可见时立即检查一次
    document.addEventListener('visibilitychange', function() {
        if (!document.hidden) {
            window.__checkAccountHealth();
        }
    });

    console.log('[P0模块] 已加载', { ROLE, API_BASE });
})();
