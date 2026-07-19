/* ====================================================================
 * P0 V2 新业务功能模块（F-1 ~ F-6）
 * - F-1 申请时间线智能提醒
 * - F-2 申请进度看板（含 iCal 导出）
 * - F-3 知识库智能推荐（收藏夹）
 * - F-4 智能问题模板与主动追问
 * - F-5 智能消息分类
 * - F-6 AI 模拟面试官
 * ====================================================================
 * 数据来源: 后端 API
 *   /api/application-timeline/...
 *   /api/favorites/...
 *   /api/messages/classify
 *   /api/mock-interview/...
 * ====================================================================
 */

(function() {
    'use strict';

    if (!window.P0Modules) window.P0Modules = {};
    if (!window.__aiCallableFunctions) window.__aiCallableFunctions = {};

    const API_BASE = window.API_BASE || '';
    const ROLE = window.ROLE || 'client';

    // ============================
    // 工具函数
    // ============================
    async function apiRequest(url, options = {}) {
        const token = localStorage.getItem('rag-auth-token') || localStorage.getItem('consultant-auth-token') || localStorage.getItem('auth_token') || '';
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
            console.error('[P0-V2] API请求失败:', url, e);
            throw e;
        }
    }

    function showToast(message, type = 'info') {
        if (typeof window.showToast === 'function') {
            window.showToast(message, type);
        } else {
            console.log(`[Toast ${type}] ${message}`);
        }
    }

    function escapeHtml(s) {
        if (s == null) return '';
        return String(s).replace(/[&<>"']/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[c]));
    }

    // ============================
    // F-1 申请时间线智能提醒
    // ============================
    const ApplicationTimeline = {
        meta: {
            name: 'ApplicationTimeline',
            version: '1.0.0',
            description: '申请时间线智能提醒：管理多所学校的申请截止日期、状态、倒计时',
            author: 'frontend-team',
            category: 'productivity',
        },
        state: {
            items: [],
            upcoming: [],
            activeView: 'list', // list / upcoming
        },

        async load() {
            try {
                const [list, upcoming] = await Promise.all([
                    apiRequest('/api/application-timeline/list'),
                    apiRequest('/api/application-timeline/upcoming?days=60').catch(() => []),
                ]);
                this.state.items = Array.isArray(list) ? list : [];
                this.state.upcoming = Array.isArray(upcoming) ? upcoming : [];
                this.render();
                return { success: true, count: this.state.items.length };
            } catch (e) {
                console.error('[F-1 申请时间线] 加载失败:', e);
                return { success: false, error: e.message };
            }
        },

        async add(item) {
            try {
                const result = await apiRequest('/api/application-timeline/add', {
                    method: 'POST',
                    body: JSON.stringify(item),
                });
                await this.load();
                showToast(result.message || '已添加到时间线', 'success');
                return { success: true, id: result.id };
            } catch (e) {
                showToast('添加失败: ' + e.message, 'error');
                return { success: false, error: e.message };
            }
        },

        async update(itemId, updates) {
            try {
                await apiRequest(`/api/application-timeline/update/${itemId}`, {
                    method: 'PUT',
                    body: JSON.stringify(updates),
                });
                await this.load();
                return { success: true };
            } catch (e) {
                showToast('更新失败: ' + e.message, 'error');
                return { success: false, error: e.message };
            }
        },

        async remove(itemId) {
            if (!confirm('确定删除此申请记录？')) return { success: false };
            try {
                await apiRequest(`/api/application-timeline/delete/${itemId}`, { method: 'DELETE' });
                await this.load();
                showToast('已删除', 'success');
                return { success: true };
            } catch (e) {
                showToast('删除失败: ' + e.message, 'error');
                return { success: false, error: e.message };
            }
        },

        async changeStatus(itemId, newStatus) {
            const item = this.state.items.find(i => i.id === itemId);
            if (!item) return;
            return await this.update(itemId, { status: newStatus });
        },

        show() {
            this._createDialog();
        },

        _createDialog() {
            const old = document.getElementById('f1-timeline-dialog');
            if (old) old.remove();
            const html = `
                <div id="f1-timeline-dialog" style="position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9500;display:flex;align-items:center;justify-content:center;">
                    <div style="background:#fff;border-radius:12px;width:900px;max-width:95vw;height:85vh;display:flex;flex-direction:column;box-shadow:0 20px 60px rgba(0,0,0,.3);">
                        <div style="padding:20px;border-bottom:1px solid #e5e7eb;display:flex;justify-content:space-between;align-items:center;">
                            <h2 style="margin:0;font-size:20px;">📅 申请时间线</h2>
                            <div style="display:flex;gap:8px;">
                                <button id="f1-btn-add" style="padding:8px 16px;background:#3b82f6;color:#fff;border:none;border-radius:6px;cursor:pointer;">+ 添加申请</button>
                                <button id="f1-btn-refresh" style="padding:8px 16px;background:#10b981;color:#fff;border:none;border-radius:6px;cursor:pointer;">🔄 刷新</button>
                                <button id="f1-btn-dashboard" style="padding:8px 16px;background:#a855f7;color:#fff;border:none;border-radius:6px;cursor:pointer;">📊 看板</button>
                                <button id="f1-btn-close" style="background:none;border:none;font-size:24px;cursor:pointer;color:#666;">✕</button>
                            </div>
                        </div>
                        <div style="padding:12px 20px;border-bottom:1px solid #e5e7eb;display:flex;gap:8px;">
                            <button class="f1-view-btn active" data-view="list" style="padding:6px 12px;background:#3b82f6;color:#fff;border:none;border-radius:4px;cursor:pointer;">全部 (${this.state.items.length})</button>
                            <button class="f1-view-btn" data-view="upcoming" style="padding:6px 12px;background:#fff;color:#374151;border:1px solid #d1d5db;border-radius:4px;cursor:pointer;">即将到期 (${this.state.upcoming.length})</button>
                        </div>
                        <div id="f1-timeline-body" style="flex:1;overflow-y:auto;padding:20px;"></div>
                    </div>
                </div>
            `;
            const div = document.createElement('div');
            div.innerHTML = html;
            document.body.appendChild(div.firstElementChild);

            document.getElementById('f1-btn-close').onclick = () => this.hide();
            document.getElementById('f1-btn-add').onclick = () => this._showAddForm();
            document.getElementById('f1-btn-refresh').onclick = () => this.load();
            document.getElementById('f1-btn-dashboard').onclick = () => {
                this.hide();
                if (window.P0Modules && window.P0Modules.ApplicationDashboard) {
                    window.P0Modules.ApplicationDashboard.show();
                }
            };
            document.querySelectorAll('.f1-view-btn').forEach(btn => {
                btn.onclick = () => {
                    document.querySelectorAll('.f1-view-btn').forEach(b => {
                        b.classList.remove('active');
                        b.style.background = '#fff';
                        b.style.color = '#374151';
                    });
                    btn.classList.add('active');
                    btn.style.background = '#3b82f6';
                    btn.style.color = '#fff';
                    this.state.activeView = btn.dataset.view;
                    this.render();
                };
            });
            this.load();
        },

        hide() {
            const dialog = document.getElementById('f1-timeline-dialog');
            if (dialog) dialog.remove();
        },

        _showAddForm() {
            const old = document.getElementById('f1-add-dialog');
            if (old) old.remove();
            const html = `
                <div id="f1-add-dialog" style="position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9600;display:flex;align-items:center;justify-content:center;">
                    <div style="background:#fff;border-radius:12px;padding:24px;width:500px;max-width:90vw;max-height:90vh;overflow-y:auto;">
                        <h3 style="margin:0 0 16px;">添加申请目标</h3>
                        <div style="margin-bottom:12px;">
                            <label style="display:block;font-size:13px;color:#374151;margin-bottom:4px;">学校名称 *</label>
                            <input id="f1-school" type="text" placeholder="如:Harvard, MIT" style="width:100%;padding:8px;border:1px solid #d1d5db;border-radius:6px;box-sizing:border-box;" />
                        </div>
                        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px;">
                            <div>
                                <label style="display:block;font-size:13px;color:#374151;margin-bottom:4px;">目标国家</label>
                                <input id="f1-country" type="text" placeholder="美国" style="width:100%;padding:8px;border:1px solid #d1d5db;border-radius:6px;box-sizing:border-box;" />
                            </div>
                            <div>
                                <label style="display:block;font-size:13px;color:#374151;margin-bottom:4px;">目标阶段</label>
                                <select id="f1-level" style="width:100%;padding:8px;border:1px solid #d1d5db;border-radius:6px;">
                                    <option value="本科">本科</option>
                                    <option value="硕士" selected>硕士</option>
                                    <option value="博士">博士</option>
                                    <option value="MBA">MBA</option>
                                </select>
                            </div>
                        </div>
                        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px;">
                            <div>
                                <label style="display:block;font-size:13px;color:#374151;margin-bottom:4px;">专业</label>
                                <input id="f1-major" type="text" placeholder="Computer Science" style="width:100%;padding:8px;border:1px solid #d1d5db;border-radius:6px;box-sizing:border-box;" />
                            </div>
                            <div>
                                <label style="display:block;font-size:13px;color:#374151;margin-bottom:4px;">申请轮次</label>
                                <select id="f1-round" style="width:100%;padding:8px;border:1px solid #d1d5db;border-radius:6px;">
                                    <option value="">无</option>
                                    <option value="ED">ED</option>
                                    <option value="EA">EA</option>
                                    <option value="RD">RD</option>
                                    <option value="Rolling">Rolling</option>
                                </select>
                            </div>
                        </div>
                        <div style="margin-bottom:12px;">
                            <label style="display:block;font-size:13px;color:#374151;margin-bottom:4px;">截止日期 *</label>
                            <input id="f1-deadline" type="date" style="width:100%;padding:8px;border:1px solid #d1d5db;border-radius:6px;box-sizing:border-box;" />
                        </div>
                        <div style="margin-bottom:12px;">
                            <label style="display:block;font-size:13px;color:#374151;margin-bottom:4px;">优先级</label>
                            <select id="f1-priority" style="width:100%;padding:8px;border:1px solid #d1d5db;border-radius:6px;">
                                <option value="high">高 (冲刺)</option>
                                <option value="medium" selected>中 (主申)</option>
                                <option value="low">低 (保底)</option>
                            </select>
                        </div>
                        <div style="margin-bottom:12px;">
                            <label style="display:block;font-size:13px;color:#374151;margin-bottom:4px;">备注</label>
                            <textarea id="f1-notes" rows="2" style="width:100%;padding:8px;border:1px solid #d1d5db;border-radius:6px;box-sizing:border-box;"></textarea>
                        </div>
                        <div style="display:flex;gap:8px;margin-top:16px;">
                            <button id="f1-add-cancel" style="flex:1;padding:10px;background:#f3f4f6;color:#374151;border:none;border-radius:6px;cursor:pointer;">取消</button>
                            <button id="f1-add-confirm" style="flex:1;padding:10px;background:#3b82f6;color:#fff;border:none;border-radius:6px;cursor:pointer;">添加</button>
                        </div>
                    </div>
                </div>
            `;
            const div = document.createElement('div');
            div.innerHTML = html;
            document.body.appendChild(div.firstElementChild);

            document.getElementById('f1-add-cancel').onclick = () => {
                document.getElementById('f1-add-dialog').remove();
            };
            document.getElementById('f1-add-confirm').onclick = async () => {
                const school = document.getElementById('f1-school').value.trim();
                const deadline = document.getElementById('f1-deadline').value;
                if (!school || !deadline) {
                    showToast('请填写学校名称和截止日期', 'error');
                    return;
                }
                const result = await this.add({
                    school_name: school,
                    target_country: document.getElementById('f1-country').value.trim(),
                    target_level: document.getElementById('f1-level').value,
                    major_name: document.getElementById('f1-major').value.trim(),
                    round: document.getElementById('f1-round').value,
                    deadline: deadline,
                    priority: document.getElementById('f1-priority').value,
                    notes: document.getElementById('f1-notes').value.trim(),
                });
                if (result.success) {
                    document.getElementById('f1-add-dialog').remove();
                }
            };
        },

        render() {
            const body = document.getElementById('f1-timeline-body');
            if (!body) return;
            const items = this.state.activeView === 'upcoming' ? this.state.upcoming : this.state.items;
            if (!items || items.length === 0) {
                body.innerHTML = `
                    <div style="text-align:center;padding:60px 20px;color:#9ca3af;">
                        <div style="font-size:48px;margin-bottom:12px;">📅</div>
                        <p>${this.state.activeView === 'upcoming' ? '60天内没有即将到期的申请' : '暂无申请记录，点击右上角添加'}</p>
                    </div>
                `;
                return;
            }
            const today = new Date();
            body.innerHTML = `
                <div style="display:grid;gap:12px;">
                    ${items.map(item => this._renderItem(item, today)).join('')}
                </div>
            `;
            // 绑定按钮
            body.querySelectorAll('[data-f1-action]').forEach(btn => {
                btn.onclick = () => {
                    const action = btn.dataset.f1Action;
                    const id = btn.dataset.id;
                    if (action === 'delete') this.remove(id);
                    else if (action.startsWith('status-')) this.changeStatus(id, action.replace('status-', ''));
                };
            });
        },

        _renderItem(item, today) {
            const ddl = new Date(item.deadline);
            const daysLeft = Math.ceil((ddl - today) / 86400000);
            const urgency = daysLeft <= 7 ? 'critical' : (daysLeft <= 15 ? 'warning' : (daysLeft <= 30 ? 'normal' : 'safe'));
            const statusMap = {
                pending: { label: '待提交', color: '#f59e0b' },
                submitted: { label: '已提交', color: '#3b82f6' },
                accepted: { label: '已录取', color: '#10b981' },
                rejected: { label: '已拒绝', color: '#ef4444' },
                waitlist: { label: 'Waitlist', color: '#a855f7' },
            };
            const status = statusMap[item.status] || statusMap.pending;
            const priorityMap = { high: '🔴 冲刺', medium: '🟡 主申', low: '🟢 保底' };
            return `
                <div style="background:#fff;border:1px solid #e5e7eb;border-left:4px solid ${urgency === 'critical' ? '#ef4444' : urgency === 'warning' ? '#f59e0b' : urgency === 'normal' ? '#3b82f6' : '#10b981'};border-radius:8px;padding:16px;">
                    <div style="display:flex;justify-content:space-between;align-items:start;">
                        <div style="flex:1;">
                            <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
                                <h4 style="margin:0;font-size:16px;color:#1f2937;">${escapeHtml(item.school_name)}</h4>
                                <span style="background:${status.color};color:#fff;padding:2px 8px;border-radius:10px;font-size:11px;">${status.label}</span>
                                <span style="background:#f3f4f6;color:#374151;padding:2px 8px;border-radius:10px;font-size:11px;">${priorityMap[item.priority] || '🟡 主申'}</span>
                            </div>
                            <div style="font-size:13px;color:#6b7280;margin-bottom:4px;">
                                ${escapeHtml(item.target_country || '')} · ${escapeHtml(item.target_level || '')} ${item.major_name ? '· ' + escapeHtml(item.major_name) : ''} ${item.round ? '· ' + escapeHtml(item.round) : ''}
                            </div>
                            ${item.notes ? `<div style="font-size:12px;color:#6b7280;font-style:italic;margin-top:4px;">📝 ${escapeHtml(item.notes)}</div>` : ''}
                        </div>
                        <div style="text-align:right;margin-left:16px;">
                            <div style="font-size:24px;font-weight:bold;color:${urgency === 'critical' ? '#ef4444' : urgency === 'warning' ? '#f59e0b' : '#1f2937'};">
                                ${daysLeft >= 0 ? daysLeft : '已过'}
                            </div>
                            <div style="font-size:11px;color:#6b7280;">${daysLeft >= 0 ? '天后截止' : '天'}</div>
                            <div style="font-size:12px;color:#6b7280;margin-top:4px;">${item.deadline}</div>
                        </div>
                    </div>
                    <div style="margin-top:12px;padding-top:12px;border-top:1px solid #f3f4f6;display:flex;gap:6px;flex-wrap:wrap;">
                        <select data-f1-action="status-pending" data-id="${item.id}" style="padding:4px 8px;font-size:12px;border:1px solid #d1d5db;border-radius:4px;">
                            <option value="">切换状态...</option>
                            <option value="pending">待提交</option>
                            <option value="submitted">已提交</option>
                            <option value="accepted">已录取</option>
                            <option value="rejected">已拒绝</option>
                            <option value="waitlist">Waitlist</option>
                        </select>
                        <button data-f1-action="delete" data-id="${item.id}" style="margin-left:auto;padding:4px 12px;background:#fee2e2;color:#dc2626;border:none;border-radius:4px;cursor:pointer;font-size:12px;">🗑️ 删除</button>
                    </div>
                </div>
            `;
        },

        callable: {
            addApplication: {
                description: '添加用户的申请目标到时间线（AI 在对话中识别到目标学校时调用）',
                parameters: {
                    school_name: { type: 'string', description: '学校名称，如 Harvard、MIT' },
                    target_country: { type: 'string', description: '目标国家，如 美国、英国' },
                    target_level: { type: 'string', description: '目标阶段，本科/硕士/博士' },
                    deadline: { type: 'string', description: '截止日期 YYYY-MM-DD' },
                    major_name: { type: 'string', description: '专业' },
                    priority: { type: 'string', description: '优先级 high/medium/low' },
                },
                execute: async function(params) {
                    if (!params.school_name || !params.deadline) {
                        return { success: false, message: '缺少学校名称或截止日期' };
                    }
                    return await ApplicationTimeline.add({
                        school_name: params.school_name,
                        target_country: params.target_country || '',
                        target_level: params.target_level || '硕士',
                        major_name: params.major_name || '',
                        deadline: params.deadline,
                        priority: params.priority || 'medium',
                    });
                },
            },
            showApplicationTimeline: {
                description: '打开申请时间线管理界面',
                parameters: {},
                execute: function() {
                    ApplicationTimeline.show();
                    return { success: true, message: '申请时间线已打开' };
                },
            },
        },
    };

    // ============================
    // F-2 申请进度看板
    // ============================
    const ApplicationDashboard = {
        meta: {
            name: 'ApplicationDashboard',
            version: '1.0.0',
            description: '申请进度可视化看板：看板视图、时间线视图、iCal 导出',
            author: 'frontend-team',
            category: 'analytics',
        },
        state: {
            view: 'kanban', // kanban / timeline
            items: [],
        },

        async load() {
            try {
                const data = await apiRequest('/api/application-timeline/list');
                this.state.items = Array.isArray(data) ? data : [];
                if (window.P0Modules.ApplicationTimeline) {
                    window.P0Modules.ApplicationTimeline.state.items = data || [];
                }
                this.render();
                return { success: true, count: this.state.items.length };
            } catch (e) {
                console.error('[F-2 看板] 加载失败:', e);
                return { success: false, error: e.message };
            }
        },

        show() {
            const old = document.getElementById('f2-dashboard-dialog');
            if (old) old.remove();
            const html = `
                <div id="f2-dashboard-dialog" style="position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9500;display:flex;align-items:center;justify-content:center;">
                    <div style="background:#fff;border-radius:12px;width:95vw;max-width:1400px;height:90vh;display:flex;flex-direction:column;box-shadow:0 20px 60px rgba(0,0,0,.3);">
                        <div style="padding:20px;border-bottom:1px solid #e5e7eb;display:flex;justify-content:space-between;align-items:center;">
                            <h2 style="margin:0;font-size:20px;">📊 申请进度看板</h2>
                            <div style="display:flex;gap:8px;">
                                <button id="f2-view-kanban" style="padding:8px 16px;background:#3b82f6;color:#fff;border:none;border-radius:6px;cursor:pointer;">看板视图</button>
                                <button id="f2-view-timeline" style="padding:8px 16px;background:#fff;color:#374151;border:1px solid #d1d5db;border-radius:6px;cursor:pointer;">时间线视图</button>
                                <button id="f2-export-ical" style="padding:8px 16px;background:#10b981;color:#fff;border:none;border-radius:6px;cursor:pointer;">📥 导出 iCal</button>
                                <button id="f2-refresh" style="padding:8px 16px;background:#a855f7;color:#fff;border:none;border-radius:6px;cursor:pointer;">🔄</button>
                                <button id="f2-close" style="background:none;border:none;font-size:24px;cursor:pointer;color:#666;">✕</button>
                            </div>
                        </div>
                        <div id="f2-dashboard-body" style="flex:1;overflow-y:auto;padding:20px;"></div>
                    </div>
                </div>
            `;
            const div = document.createElement('div');
            div.innerHTML = html;
            document.body.appendChild(div.firstElementChild);

            document.getElementById('f2-close').onclick = () => this.hide();
            document.getElementById('f2-refresh').onclick = () => this.load();
            document.getElementById('f2-view-kanban').onclick = () => { this.state.view = 'kanban'; this.render(); };
            document.getElementById('f2-view-timeline').onclick = () => { this.state.view = 'timeline'; this.render(); };
            document.getElementById('f2-export-ical').onclick = () => this.exportICal();
            this.load();
        },

        hide() {
            const dialog = document.getElementById('f2-dashboard-dialog');
            if (dialog) dialog.remove();
        },

        render() {
            const body = document.getElementById('f2-dashboard-body');
            if (!body) return;
            if (this.state.view === 'kanban') {
                this._renderKanban(body);
            } else {
                this._renderTimeline(body);
            }
        },

        _renderKanban(container) {
            const items = this.state.items;
            const columns = {
                pending: { label: '📋 待提交', color: '#f59e0b', items: [] },
                submitted: { label: '✉️ 已提交', color: '#3b82f6', items: [] },
                waitlist: { label: '⏳ Waitlist', color: '#a855f7', items: [] },
                accepted: { label: '🎉 已录取', color: '#10b981', items: [] },
                rejected: { label: '❌ 已拒绝', color: '#ef4444', items: [] },
            };
            items.forEach(item => {
                if (columns[item.status]) columns[item.status].items.push(item);
                else columns.pending.items.push(item);
            });
            const today = new Date();
            container.innerHTML = `
                <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:12px;height:100%;">
                    ${Object.entries(columns).map(([key, col]) => `
                        <div data-status="${key}" style="background:#f9fafb;border-radius:8px;padding:12px;display:flex;flex-direction:column;border-top:3px solid ${col.color};">
                            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid #e5e7eb;">
                                <span style="font-weight:600;font-size:14px;">${col.label}</span>
                                <span style="background:${col.color};color:#fff;border-radius:10px;padding:2px 8px;font-size:12px;font-weight:600;">${col.items.length}</span>
                            </div>
                            <div class="f2-cards" style="flex:1;overflow-y:auto;display:flex;flex-direction:column;gap:8px;">
                                ${col.items.map(item => this._renderCard(item, today)).join('')}
                                ${col.items.length === 0 ? '<div style="text-align:center;color:#9ca3af;font-size:12px;padding:20px 0;">暂无</div>' : ''}
                            </div>
                        </div>
                    `).join('')}
                </div>
            `;
            // 状态切换
            container.querySelectorAll('.f2-card-status-select').forEach(sel => {
                sel.onchange = async (e) => {
                    const id = e.target.dataset.id;
                    const newStatus = e.target.value;
                    if (newStatus && window.P0Modules.ApplicationTimeline) {
                        await window.P0Modules.ApplicationTimeline.changeStatus(id, newStatus);
                        this.load();
                    }
                };
            });
        },

        _renderCard(item, today) {
            const ddl = new Date(item.deadline);
            const daysLeft = Math.ceil((ddl - today) / 86400000);
            const urgencyColor = daysLeft <= 7 ? '#ef4444' : (daysLeft <= 15 ? '#f59e0b' : (daysLeft <= 30 ? '#3b82f6' : '#10b981'));
            const priorityLabel = { high: '🔴', medium: '🟡', low: '🟢' }[item.priority] || '🟡';
            return `
                <div style="background:#fff;border:1px solid #e5e7eb;border-radius:6px;padding:10px;cursor:move;box-shadow:0 1px 3px rgba(0,0,0,.05);">
                    <div style="font-weight:600;font-size:14px;margin-bottom:4px;">${priorityLabel} ${escapeHtml(item.school_name)}</div>
                    <div style="font-size:11px;color:#6b7280;margin-bottom:4px;">${escapeHtml(item.target_country || '')} · ${escapeHtml(item.target_level || '')}</div>
                    ${item.major_name ? `<div style="font-size:11px;color:#6b7280;margin-bottom:4px;">📚 ${escapeHtml(item.major_name)}</div>` : ''}
                    ${item.round ? `<div style="font-size:11px;color:#6b7280;margin-bottom:4px;">🎯 ${escapeHtml(item.round)}</div>` : ''}
                    <div style="font-size:12px;color:${urgencyColor};font-weight:600;margin-top:6px;">
                        ⏰ ${daysLeft >= 0 ? `还有 ${daysLeft} 天` : '已过期'}
                    </div>
                    <div style="font-size:11px;color:#9ca3af;margin-top:2px;">${item.deadline}</div>
                    <select class="f2-card-status-select" data-id="${item.id}" style="margin-top:8px;width:100%;padding:3px;font-size:11px;border:1px solid #d1d5db;border-radius:3px;">
                        <option value="">移动到...</option>
                        <option value="pending">待提交</option>
                        <option value="submitted">已提交</option>
                        <option value="accepted">已录取</option>
                        <option value="rejected">已拒绝</option>
                        <option value="waitlist">Waitlist</option>
                    </select>
                </div>
            `;
        },

        _renderTimeline(container) {
            const items = this.state.items;
            if (items.length === 0) {
                container.innerHTML = '<div style="text-align:center;padding:60px;color:#9ca3af;">暂无申请记录</div>';
                return;
            }
            const today = new Date();
            const sorted = [...items].sort((a, b) => new Date(a.deadline) - new Date(b.deadline));
            const allDates = sorted.flatMap(i => [new Date(i.created_at || today), new Date(i.deadline)]);
            const minDate = new Date(Math.min(...allDates.map(d => d.getTime())));
            const maxDate = new Date(Math.max(...allDates.map(d => d.getTime())));
            const totalSpan = Math.max((maxDate - minDate) / 86400000, 1);

            container.innerHTML = `
                <div style="padding:20px;">
                    <h3 style="margin-top:0;">📅 时间线视图</h3>
                    <p style="color:#6b7280;font-size:13px;">从 ${minDate.toISOString().slice(0,10)} 到 ${maxDate.toISOString().slice(0,10)}</p>
                    <div style="margin-top:24px;">
                        ${sorted.map(item => {
                            const start = new Date(item.created_at || today);
                            const end = new Date(item.deadline);
                            const startPct = Math.max(0, ((start - minDate) / 86400000 / totalSpan) * 100);
                            const widthPct = Math.max(2, ((end - start) / 86400000 / totalSpan) * 100);
                            const statusColor = { pending: '#f59e0b', submitted: '#3b82f6', accepted: '#10b981', rejected: '#ef4444', waitlist: '#a855f7' }[item.status] || '#6b7280';
                            const daysLeft = Math.ceil((end - today) / 86400000);
                            return `
                                <div style="display:flex;align-items:center;margin-bottom:14px;">
                                    <div style="width:220px;font-size:14px;font-weight:500;">${escapeHtml(item.school_name)}</div>
                                    <div style="flex:1;background:#f3f4f6;height:28px;border-radius:4px;position:relative;min-width:200px;">
                                        <div style="position:absolute;left:${startPct}%;width:${widthPct}%;height:100%;background:${statusColor};border-radius:4px;display:flex;align-items:center;padding:0 8px;color:#fff;font-size:12px;overflow:hidden;">
                                            ${item.deadline} ${daysLeft >= 0 ? '(' + daysLeft + '天后)' : '(已过)'}
                                        </div>
                                    </div>
                                </div>
                            `;
                        }).join('')}
                    </div>
                </div>
            `;
        },

        exportICal() {
            const items = this.state.items;
            if (items.length === 0) {
                showToast('没有可导出的申请', 'warn');
                return;
            }
            let ical = 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//RAG//Application Timeline//ZH\r\nCALSCALE:GREGORIAN\r\n';
            const now = new Date().toISOString().replace(/[-:]/g, '').split('.')[0] + 'Z';
            items.forEach(item => {
                const ddl = new Date(item.deadline);
                const yyyy = ddl.getFullYear();
                const mm = String(ddl.getMonth() + 1).padStart(2, '0');
                const dd = String(ddl.getDate()).padStart(2, '0');
                const ddlStr = `${yyyy}${mm}${dd}`;
                const summary = `${item.school_name} 申请截止`;
                const desc = `${item.target_country || ''} ${item.target_level || ''} ${item.major_name || ''} 申请DDL (${item.status || 'pending'})`;
                ical += `BEGIN:VEVENT\r\n`;
                ical += `UID:${item.id}@rag-system\r\n`;
                ical += `DTSTAMP:${now}\r\n`;
                ical += `DTSTART;VALUE=DATE:${ddlStr}\r\n`;
                ical += `SUMMARY:${summary}\r\n`;
                ical += `DESCRIPTION:${desc}\r\n`;
                ical += `CATEGORIES:APPLICATION\r\n`;
                ical += `END:VEVENT\r\n`;
            });
            ical += 'END:VCALENDAR\r\n';

            const blob = new Blob([ical], { type: 'text/calendar;charset=utf-8' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `application_timeline_${new Date().toISOString().slice(0, 10)}.ics`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
            showToast('iCal 文件已导出', 'success');
        },

        callable: {
            showDashboard: {
                description: '打开申请进度看板',
                parameters: {},
                execute: function() {
                    ApplicationDashboard.show();
                    return { success: true, message: '看板已打开' };
                },
            },
            exportICal: {
                description: '导出所有申请截止日期为 iCal 文件',
                parameters: {},
                execute: function() {
                    ApplicationDashboard.exportICal();
                    return { success: true, message: 'iCal 已导出' };
                },
            },
        },
    };

    // ============================
    // F-3 知识库智能推荐（收藏夹）
    // ============================
    const KnowledgeRecommendation = {
        meta: {
            name: 'KnowledgeRecommendation',
            version: '1.0.0',
            description: '知识库智能推荐：AI 回复中插入相关文档、收藏文档、收藏夹管理',
            author: 'frontend-team',
            category: 'ai',
        },
        state: {
            recommendations: [],
            favorites: [],
            stats: { total: 0, by_category: {} },
        },

        // SSE 事件：AI 回复后展示相关文档
        onRelatedDocs(docs) {
            if (!Array.isArray(docs) || docs.length === 0) return;
            this.state.recommendations = docs;
            this._renderInline(docs);
        },

        _renderInline(docs) {
            // 在最后一个 AI 消息后插入推荐
            const lastAnswer = document.querySelector('.chat-message.ai-message:last-child .message-content');
            if (!lastAnswer) return;
            // 防止重复插入
            const existing = lastAnswer.querySelector('.kr-recommendations');
            if (existing) existing.remove();

            const recDiv = document.createElement('div');
            recDiv.className = 'kr-recommendations';
            recDiv.style.cssText = 'margin-top:12px;padding:12px;background:#eff6ff;border-radius:8px;border:1px solid #bfdbfe;';
            recDiv.innerHTML = `
                <div style="font-size:13px;font-weight:600;color:#1e40af;margin-bottom:8px;">📚 相关资料推荐</div>
                ${docs.slice(0, 3).map(d => `
                    <div class="kr-card" data-doc-id="${escapeHtml(d.id || '')}" style="background:#fff;border-radius:6px;padding:8px 12px;margin-bottom:6px;display:flex;justify-content:space-between;align-items:start;gap:8px;">
                        <div style="flex:1;min-width:0;">
                            <div style="font-size:13px;font-weight:500;color:#1f2937;">${escapeHtml(d.title || d.doc_title || '相关文档')}</div>
                            ${d.summary ? `<div style="font-size:12px;color:#6b7280;margin-top:2px;">${escapeHtml(d.summary).slice(0, 100)}</div>` : ''}
                        </div>
                        <button class="kr-fav-btn" data-doc='${escapeHtml(JSON.stringify(d))}' style="background:#fbbf24;color:#fff;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:12px;white-space:nowrap;">⭐ 收藏</button>
                    </div>
                `).join('')}
            `;
            lastAnswer.appendChild(recDiv);
            recDiv.querySelectorAll('.kr-fav-btn').forEach(btn => {
                btn.onclick = () => {
                    const d = JSON.parse(btn.dataset.doc);
                    this.favorite(d.id || d.doc_id, d.title || d.doc_title, d.source || d.category || 'other', d.path || d.doc_path || '', d.summary || d.doc_summary || '');
                };
            });
        },

        async favorite(docId, title, category, path, summary) {
            if (!docId) {
                showToast('文档ID缺失', 'error');
                return;
            }
            try {
                await apiRequest('/api/favorites/add', {
                    method: 'POST',
                    body: JSON.stringify({
                        doc_id: String(docId),
                        doc_title: title || '未命名文档',
                        category: category || 'other',
                        doc_path: path || '',
                        doc_summary: summary || '',
                    }),
                });
                showToast('已收藏', 'success');
                this.loadFavorites();
            } catch (e) {
                showToast('收藏失败: ' + e.message, 'error');
            }
        },

        async loadFavorites() {
            try {
                const [list, stats] = await Promise.all([
                    apiRequest('/api/favorites/list'),
                    apiRequest('/api/favorites/stats').catch(() => ({ total: 0, by_category: {} })),
                ]);
                this.state.favorites = Array.isArray(list) ? list : [];
                this.state.stats = stats || { total: 0, by_category: {} };
                this._renderFavorites();
                return { success: true, count: this.state.favorites.length };
            } catch (e) {
                console.error('[F-3 收藏] 加载失败:', e);
                return { success: false, error: e.message };
            }
        },

        async remove(favId) {
            if (!confirm('确定删除此收藏？')) return;
            try {
                await apiRequest(`/api/favorites/delete/${favId}`, { method: 'DELETE' });
                showToast('已删除', 'success');
                this.loadFavorites();
            } catch (e) {
                showToast('删除失败: ' + e.message, 'error');
            }
        },

        async search(keyword) {
            if (!keyword) {
                return { success: false, message: '请输入关键词', data: [] };
            }
            try {
                const data = await apiRequest(`/api/favorites/search?keyword=${encodeURIComponent(keyword)}`);
                return { success: true, count: data.length, data };
            } catch (e) {
                return { success: false, error: e.message, data: [] };
            }
        },

        show() {
            const old = document.getElementById('f3-favorites-dialog');
            if (old) old.remove();
            const html = `
                <div id="f3-favorites-dialog" style="position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9500;display:flex;align-items:center;justify-content:center;">
                    <div style="background:#fff;border-radius:12px;width:800px;max-width:95vw;height:80vh;display:flex;flex-direction:column;box-shadow:0 20px 60px rgba(0,0,0,.3);">
                        <div style="padding:20px;border-bottom:1px solid #e5e7eb;display:flex;justify-content:space-between;align-items:center;">
                            <h2 style="margin:0;font-size:20px;">⭐ 我的资料库</h2>
                            <div style="display:flex;gap:8px;">
                                <input id="f3-search-input" type="text" placeholder="搜索收藏..." style="padding:6px 12px;border:1px solid #d1d5db;border-radius:6px;width:200px;" />
                                <button id="f3-search-btn" style="padding:6px 12px;background:#3b82f6;color:#fff;border:none;border-radius:6px;cursor:pointer;">搜索</button>
                                <button id="f3-close" style="background:none;border:none;font-size:24px;cursor:pointer;color:#666;">✕</button>
                            </div>
                        </div>
                        <div id="f3-stats-bar" style="padding:12px 20px;border-bottom:1px solid #e5e7eb;background:#f9fafb;"></div>
                        <div id="f3-favorites-body" style="flex:1;overflow-y:auto;padding:20px;"></div>
                    </div>
                </div>
            `;
            const div = document.createElement('div');
            div.innerHTML = html;
            document.body.appendChild(div.firstElementChild);

            document.getElementById('f3-close').onclick = () => this.hide();
            document.getElementById('f3-search-btn').onclick = () => this._searchAndRender();
            document.getElementById('f3-search-input').onkeypress = (e) => {
                if (e.key === 'Enter') this._searchAndRender();
            };
            this.loadFavorites();
        },

        hide() {
            const dialog = document.getElementById('f3-favorites-dialog');
            if (dialog) dialog.remove();
        },

        async _searchAndRender() {
            const keyword = document.getElementById('f3-search-input').value.trim();
            if (!keyword) {
                this.loadFavorites();
                return;
            }
            const result = await this.search(keyword);
            this._renderFavoritesList(result.data || []);
        },

        _renderFavorites() {
            // 渲染统计
            const stats = this.state.stats;
            const statsBar = document.getElementById('f3-stats-bar');
            if (statsBar) {
                const cats = stats.by_category || {};
                statsBar.innerHTML = `
                    <div style="display:flex;gap:12px;flex-wrap:wrap;font-size:13px;">
                        <span style="font-weight:600;">📊 共 ${stats.total} 项收藏</span>
                        ${Object.entries(cats).map(([cat, cnt]) => `<span style="background:#e5e7eb;padding:2px 8px;border-radius:10px;">${this._categoryLabel(cat)}: ${cnt}</span>`).join('')}
                    </div>
                `;
            }
            this._renderFavoritesList(this.state.favorites);
        },

        _renderFavoritesList(list) {
            const body = document.getElementById('f3-favorites-body');
            if (!body) return;
            if (!list || list.length === 0) {
                body.innerHTML = '<div style="text-align:center;padding:60px;color:#9ca3af;"><div style="font-size:48px;">📂</div><p>暂无收藏</p></div>';
                return;
            }
            body.innerHTML = `
                <div style="display:grid;gap:8px;">
                    ${list.map(f => `
                        <div style="background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:12px;display:flex;justify-content:space-between;align-items:start;gap:8px;">
                            <div style="flex:1;min-width:0;">
                                <div style="font-size:13px;font-weight:600;color:#1f2937;margin-bottom:4px;">
                                    <span style="background:#e5e7eb;padding:2px 6px;border-radius:4px;font-size:11px;margin-right:6px;">${this._categoryLabel(f.category)}</span>
                                    ${escapeHtml(f.doc_title)}
                                </div>
                                ${f.doc_summary ? `<div style="font-size:12px;color:#6b7280;">${escapeHtml(f.doc_summary).slice(0, 200)}</div>` : ''}
                                <div style="font-size:11px;color:#9ca3af;margin-top:4px;">收藏于 ${f.created_at ? new Date(f.created_at).toLocaleString('zh-CN') : '-'}</div>
                            </div>
                            <button data-fav-id="${f.id}" class="f3-remove-btn" style="background:#fee2e2;color:#dc2626;border:none;padding:6px 12px;border-radius:4px;cursor:pointer;font-size:12px;white-space:nowrap;">删除</button>
                        </div>
                    `).join('')}
                </div>
            `;
            body.querySelectorAll('.f3-remove-btn').forEach(btn => {
                btn.onclick = () => this.remove(btn.dataset.favId);
            });
        },

        _categoryLabel(cat) {
            const map = {
                policy: '📋 政策',
                case: '💼 案例',
                data: '📊 数据',
                school: '🏫 学校',
                visa: '🛂 签证',
                cost: '💰 费用',
                other: '📄 其他',
            };
            return map[cat] || `📄 ${cat}`;
        },

        callable: {
            showFavorites: {
                description: '打开我的资料库（收藏夹）',
                parameters: {},
                execute: function() {
                    KnowledgeRecommendation.show();
                    return { success: true, message: '收藏夹已打开' };
                },
            },
            searchFavorites: {
                description: '搜索用户收藏的资料',
                parameters: { keyword: { type: 'string', description: '搜索关键词' } },
                execute: async function(params) {
                    if (!params.keyword) {
                        return { success: false, message: '请提供搜索关键词', data: [] };
                    }
                    return await KnowledgeRecommendation.search(params.keyword);
                },
            },
        },
    };

    // ============================
    // F-4 智能问题模板与主动追问
    // ============================
    const QuestionTemplate = {
        meta: {
            name: 'QuestionTemplate',
            version: '1.0.0',
            description: '智能问题模板：5阶段20+模板问题、AI 主动追问、模板问题快捷发送',
            author: 'frontend-team',
            category: 'ai',
        },
        templates: {
            '选校阶段': [
                '我应该选择综合大学还是文理学院？',
                '美国 TOP30 学校中哪些对中国学生友好？',
                '英国 G5 的录取要求是什么？',
                '我的 GPA 3.5，能申请到什么排名的学校？',
                '计算机专业美国和欧洲哪个更好？',
            ],
            '文书阶段': [
                'Personal Statement 应该怎么写？',
                '推荐信应该找谁写？',
                '如何写出有特色的文书？',
                'Common App 文书有什么注意事项？',
                '文书的初稿到终稿要修改几遍？',
            ],
            '申请阶段': [
                '美国 ED 和 RD 的区别？',
                '申请需要哪些材料？',
                '申请费一般多少？',
                'Common App 如何填写？',
                '加州大学系统怎么申请？',
            ],
            '签证阶段': [
                'F-1 签证需要准备什么材料？',
                '签证面试会问什么问题？',
                '签证被拒后如何申诉？',
                'SEVIS Fee 如何缴纳？',
                '美国签证和英国签证的区别？',
            ],
            '行前准备': [
                '美国租房需要注意什么？',
                '留学需要带哪些东西？',
                '美国银行账户怎么开？',
                '选课有什么技巧？',
                '如何快速适应留学生活？',
            ],
        },

        detectCurrentStage(profile) {
            if (!profile) return '选校阶段';
            const hasCountry = !!(profile.target_country);
            const hasLang = !!(profile.language_score);
            const hasSchool = !!(profile.education || profile.current_school);
            if (!hasCountry) return '选校阶段';
            if (!hasLang) return '文书阶段';
            if (!hasSchool) return '申请阶段';
            return '签证阶段';
        },

        show() {
            const chatInput = document.getElementById('messageInput');
            if (!chatInput) {
                showToast('请先进入AI对话', 'warn');
                return;
            }
            // 移除旧的
            const old = document.getElementById('qt-templates-bar');
            if (old) old.remove();

            // 获取用户阶段
            let profile = {};
            if (window.P0Modules && window.P0Modules.ProfileForm && window.P0Modules.ProfileForm.state) {
                profile = window.P0Modules.ProfileForm.state.profile || {};
            }
            const stage = this.detectCurrentStage(profile);
            const templates = this.templates[stage] || this.templates['选校阶段'];

            const bar = document.createElement('div');
            bar.id = 'qt-templates-bar';
            bar.style.cssText = 'display:flex;gap:8px;padding:10px;overflow-x:auto;background:linear-gradient(135deg,#eef2ff 0%,#e0e7ff 100%);border:1px solid #c7d2fe;border-radius:8px;margin:8px 0;align-items:center;';
            bar.innerHTML = `
                <span style="font-size:12px;color:#4338ca;font-weight:600;white-space:nowrap;">💡 ${stage}：</span>
                ${templates.map((t, i) => `
                    <button class="qt-chip" data-question="${escapeHtml(t)}" style="padding:5px 12px;background:#fff;border:1px solid #c7d2fe;border-radius:14px;cursor:pointer;font-size:12px;white-space:nowrap;color:#4338ca;">
                        ${escapeHtml(t)}
                    </button>
                `).join('')}
                <button class="qt-close" style="margin-left:auto;background:none;border:none;cursor:pointer;color:#6b7280;font-size:14px;padding:2px 6px;">✕</button>
            `;
            // 找到 chatInput 的父元素
            const parent = chatInput.parentElement;
            if (parent) {
                parent.insertBefore(bar, parent.firstChild);
            } else {
                chatInput.insertAdjacentElement('beforebegin', bar);
            }

            bar.querySelectorAll('.qt-chip').forEach(btn => {
                btn.onclick = () => {
                    chatInput.value = btn.dataset.question;
                    chatInput.focus();
                    bar.remove();
                };
            });
            bar.querySelector('.qt-close').onclick = () => bar.remove();
        },

        // 主动追问 - 在对话中显示追问建议
        showFollowUps(questions) {
            if (!Array.isArray(questions) || questions.length === 0) return;
            const chatInput = document.getElementById('messageInput');
            if (!chatInput) return;

            // 移除旧的
            const old = document.getElementById('qt-followup-bar');
            if (old) old.remove();

            const bar = document.createElement('div');
            bar.id = 'qt-followup-bar';
            bar.style.cssText = 'display:flex;flex-direction:column;gap:6px;padding:10px 12px;background:linear-gradient(135deg,#fef3c7 0%,#fde68a 100%);border:1px solid #fcd34d;border-radius:8px;margin:8px 0;';
            bar.innerHTML = `
                <div style="display:flex;justify-content:space-between;align-items:center;">
                    <span style="font-size:12px;color:#92400e;font-weight:600;">🤔 AI 主动追问（点击快速回答）：</span>
                    <button class="qt-close" style="background:none;border:none;cursor:pointer;color:#6b7280;font-size:14px;padding:0 4px;">✕</button>
                </div>
                <div style="display:flex;flex-wrap:wrap;gap:6px;">
                    ${questions.slice(0, 4).map(q => `
                        <button class="qt-fu-chip" data-q="${escapeHtml(q)}" style="padding:5px 12px;background:#fff;border:1px solid #fcd34d;border-radius:14px;cursor:pointer;font-size:12px;color:#92400e;text-align:left;">
                            ${escapeHtml(q)}
                        </button>
                    `).join('')}
                </div>
            `;
            const parent = chatInput.parentElement;
            if (parent) {
                parent.insertBefore(bar, parent.firstChild);
            } else {
                chatInput.insertAdjacentElement('beforebegin', bar);
            }

            bar.querySelectorAll('.qt-fu-chip').forEach(btn => {
                btn.onclick = () => {
                    chatInput.value = btn.dataset.q;
                    chatInput.focus();
                    bar.remove();
                };
            });
            bar.querySelector('.qt-close').onclick = () => bar.remove();
        },

        callable: {
            showQuestionTemplates: {
                description: '显示当前申请阶段的智能问题模板',
                parameters: {},
                execute: function() {
                    QuestionTemplate.show();
                    return { success: true, message: '问题模板已显示' };
                },
            },
            suggestTemplateQuestions: {
                description: '根据申请阶段返回模板问题列表',
                parameters: { stage: { type: 'string', description: '申请阶段: 选校阶段/文书阶段/申请阶段/签证阶段/行前准备' } },
                execute: function(params) {
                    const stage = params.stage || '选校阶段';
                    const questions = QuestionTemplate.templates[stage] || [];
                    return { success: true, stage, count: questions.length, data: questions };
                },
            },
        },
    };

    // ============================
    // F-5 智能消息分类
    // ============================
    const MessageClassifier = {
        meta: {
            name: 'MessageClassifier',
            version: '1.0.0',
            description: '智能消息分类：咨询/通知/闲聊/紧急，自动分类消息',
            author: 'frontend-team',
            category: 'ai',
        },
        state: {
            categories: { 紧急: [], 咨询: [], 通知: [], 闲聊: [], 其他: [] },
            activeTab: 'all',
        },

        // 关键词分类（降级方案）
        classifyLocal(content) {
            if (!content) return { category: '其他', priority: 5 };
            const urgentWords = ['紧急', '急', '马上', '立即', '催', '尽快', '立刻'];
            const consultWords = ['请问', '咨询', '怎么', '如何', '吗', '?', '？', '能不能'];
            const notifyWords = ['通知', '公告', '提醒', '截止', '已完成', '安排', '确认'];
            const chatWords = ['哈哈', '好的', '嗯', '哦', '谢谢', '感谢', '收到', '👍', '你好'];

            if (urgentWords.some(w => content.includes(w))) return { category: '紧急', priority: 1 };
            if (notifyWords.some(w => content.includes(w))) return { category: '通知', priority: 3 };
            if (consultWords.some(w => content.includes(w))) return { category: '咨询', priority: 2 };
            if (chatWords.some(w => content.includes(w))) return { category: '闲聊', priority: 5 };
            return { category: '其他', priority: 4 };
        },

        // 调用后端 LLM 分类
        async classifyWithAI(messages) {
            if (!Array.isArray(messages) || messages.length === 0) return [];
            try {
                const result = await apiRequest('/api/messages/classify', {
                    method: 'POST',
                    body: JSON.stringify({
                        messages: messages.map(m => ({
                            id: m.id,
                            content: m.content,
                            sender: m.sender,
                        })),
                    }),
                });
                return result;
            } catch (e) {
                // 降级到本地
                return messages.map(m => {
                    const local = this.classifyLocal(m.content);
                    return { id: m.id, content: m.content, sender: m.sender, ...local };
                });
            }
        },

        // 分类单条
        async classifySingle(content, sender) {
            try {
                const result = await apiRequest('/api/messages/classify-single', {
                    method: 'POST',
                    body: JSON.stringify({ content, sender }),
                });
                return result;
            } catch (e) {
                return { content, sender, ...this.classifyLocal(content) };
            }
        },

        renderCategoryTabs(containerId, messages) {
            const container = document.getElementById(containerId);
            if (!container) return;
            // 统计
            const counts = { 紧急: 0, 咨询: 0, 通知: 0, 闲聊: 0, 其他: 0, all: messages.length };
            messages.forEach(m => {
                const cat = m.category || '其他';
                if (counts[cat] !== undefined) counts[cat]++;
            });
            container.innerHTML = `
                <div style="display:flex;gap:6px;padding:8px 12px;border-bottom:1px solid #e5e7eb;background:#f9fafb;overflow-x:auto;">
                    <button class="msg-cat-tab active" data-cat="all" style="padding:4px 12px;background:#3b82f6;color:#fff;border:none;border-radius:14px;cursor:pointer;font-size:12px;white-space:nowrap;">
                        全部 (${counts.all})
                    </button>
                    <button class="msg-cat-tab" data-cat="紧急" style="padding:4px 12px;background:#fff;border:1px solid #ef4444;color:#ef4444;border-radius:14px;cursor:pointer;font-size:12px;white-space:nowrap;">
                        🔴 紧急 (${counts['紧急']})
                    </button>
                    <button class="msg-cat-tab" data-cat="咨询" style="padding:4px 12px;background:#fff;border:1px solid #3b82f6;color:#3b82f6;border-radius:14px;cursor:pointer;font-size:12px;white-space:nowrap;">
                        💬 咨询 (${counts['咨询']})
                    </button>
                    <button class="msg-cat-tab" data-cat="通知" style="padding:4px 12px;background:#fff;border:1px solid #10b981;color:#10b981;border-radius:14px;cursor:pointer;font-size:12px;white-space:nowrap;">
                        📢 通知 (${counts['通知']})
                    </button>
                    <button class="msg-cat-tab" data-cat="闲聊" style="padding:4px 12px;background:#fff;border:1px solid #6b7280;color:#6b7280;border-radius:14px;cursor:pointer;font-size:12px;white-space:nowrap;">
                        🗨️ 闲聊 (${counts['闲聊']})
                    </button>
                    <button class="msg-cat-tab" data-cat="其他" style="padding:4px 12px;background:#fff;border:1px solid #9ca3af;color:#9ca3af;border-radius:14px;cursor:pointer;font-size:12px;white-space:nowrap;">
                        📄 其他 (${counts['其他']})
                    </button>
                </div>
            `;
        },

        callable: {
            classifyMessage: {
                description: '对单条消息进行智能分类（紧急/咨询/通知/闲聊/其他）',
                parameters: { content: { type: 'string', description: '消息内容' } },
                execute: async function(params) {
                    if (!params.content) {
                        return { success: false, message: '请提供消息内容' };
                    }
                    return await MessageClassifier.classifySingle(params.content, params.sender);
                },
            },
            classifyMessages: {
                description: '批量分类多条消息',
                parameters: { messages: { type: 'array', description: '消息列表 [{id, content, sender}]' } },
                execute: async function(params) {
                    if (!Array.isArray(params.messages)) {
                        return { success: false, message: 'messages 必须是数组' };
                    }
                    const results = await MessageClassifier.classifyWithAI(params.messages);
                    return { success: true, count: results.length, data: results };
                },
            },
        },
    };

    // ============================
    // F-6 AI 模拟面试官
    // ============================
    const MockInterview = {
        meta: {
            name: 'MockInterview',
            version: '1.0.0',
            description: 'AI 模拟面试官：定制问题、4维度评估、面试历史',
            author: 'frontend-team',
            category: 'ai',
        },
        state: {
            current: null, // 当前面试 {id, questions}
            questionIndex: 0,
            evaluation: null,
            history: [],
        },

        async start(schoolName, major, interviewType) {
            try {
                const result = await apiRequest('/api/mock-interview/start', {
                    method: 'POST',
                    body: JSON.stringify({
                        school_name: schoolName,
                        major: major || '',
                        interview_type: interviewType || 'behavioral',
                    }),
                });
                this.state.current = { id: result.id, questions: result.questions };
                this.state.questionIndex = 0;
                this.state.evaluation = null;
                return { success: true, ...result };
            } catch (e) {
                return { success: false, error: e.message };
            }
        },

        async submitAnswer(answer) {
            if (!this.state.current) {
                return { success: false, error: '没有进行中的面试' };
            }
            try {
                const result = await apiRequest('/api/mock-interview/answer', {
                    method: 'POST',
                    body: JSON.stringify({
                        interview_id: this.state.current.id,
                        question_index: this.state.questionIndex,
                        answer: answer,
                    }),
                });
                this.state.questionIndex++;
                this.state.evaluation = result.evaluation;
                return { success: true, ...result };
            } catch (e) {
                return { success: false, error: e.message };
            }
        },

        async loadHistory() {
            try {
                const data = await apiRequest('/api/mock-interview/history');
                this.state.history = Array.isArray(data) ? data : [];
                return { success: true, count: this.state.history.length };
            } catch (e) {
                return { success: false, error: e.message };
            }
        },

        async getDetail(interviewId) {
            try {
                const data = await apiRequest(`/api/mock-interview/detail/${interviewId}`);
                return { success: true, data };
            } catch (e) {
                return { success: false, error: e.message };
            }
        },

        show() {
            const old = document.getElementById('f6-mock-dialog');
            if (old) old.remove();
            const html = `
                <div id="f6-mock-dialog" style="position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9500;display:flex;align-items:center;justify-content:center;">
                    <div style="background:#fff;border-radius:12px;width:800px;max-width:95vw;height:85vh;display:flex;flex-direction:column;box-shadow:0 20px 60px rgba(0,0,0,.3);">
                        <div style="padding:20px;border-bottom:1px solid #e5e7eb;display:flex;justify-content:space-between;align-items:center;">
                            <h2 style="margin:0;font-size:20px;">🎓 AI 模拟面试官</h2>
                            <div style="display:flex;gap:8px;">
                                <button id="f6-btn-history" style="padding:6px 12px;background:#a855f7;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:13px;">📜 历史</button>
                                <button id="f6-btn-close" style="background:none;border:none;font-size:24px;cursor:pointer;color:#666;">✕</button>
                            </div>
                        </div>
                        <div id="f6-mock-body" style="flex:1;overflow-y:auto;padding:20px;"></div>
                    </div>
                </div>
            `;
            const div = document.createElement('div');
            div.innerHTML = html;
            document.body.appendChild(div.firstElementChild);

            document.getElementById('f6-btn-close').onclick = () => this.hide();
            document.getElementById('f6-btn-history').onclick = () => this._renderHistory();
            this._renderStart();
        },

        hide() {
            const dialog = document.getElementById('f6-mock-dialog');
            if (dialog) dialog.remove();
        },

        _renderStart() {
            const body = document.getElementById('f6-mock-body');
            if (!body) return;
            body.innerHTML = `
                <div style="max-width:500px;margin:0 auto;">
                    <div style="text-align:center;padding:20px 0;">
                        <div style="font-size:48px;margin-bottom:12px;">🎓</div>
                        <h3 style="margin:0 0 8px;">开始模拟面试</h3>
                        <p style="color:#6b7280;font-size:13px;">AI 将扮演面试官，针对您的目标学校出题</p>
                    </div>
                    <div style="margin-top:24px;">
                        <label style="display:block;font-size:13px;color:#374151;margin-bottom:4px;font-weight:500;">目标学校 *</label>
                        <input id="f6-school" type="text" placeholder="如：MIT, Stanford, Oxford, CMU..." style="width:100%;padding:10px;border:1px solid #d1d5db;border-radius:6px;box-sizing:border-box;" />
                    </div>
                    <div style="margin-top:12px;">
                        <label style="display:block;font-size:13px;color:#374151;margin-bottom:4px;font-weight:500;">申请专业</label>
                        <input id="f6-major" type="text" placeholder="如：Computer Science, MBA..." style="width:100%;padding:10px;border:1px solid #d1d5db;border-radius:6px;box-sizing:border-box;" />
                    </div>
                    <div style="margin-top:12px;">
                        <label style="display:block;font-size:13px;color:#374151;margin-bottom:4px;font-weight:500;">面试类型</label>
                        <select id="f6-type" style="width:100%;padding:10px;border:1px solid #d1d5db;border-radius:6px;">
                            <option value="behavioral">行为面试 (Behavioral)</option>
                            <option value="technical">技术面试 (Technical)</option>
                            <option value="case">案例面试 (Case)</option>
                        </select>
                    </div>
                    <button id="f6-start-btn" style="margin-top:24px;width:100%;padding:14px;background:linear-gradient(135deg,#3b82f6,#2563eb);color:#fff;border:none;border-radius:8px;cursor:pointer;font-size:16px;font-weight:500;">
                        🚀 开始面试
                    </button>
                </div>
            `;
            document.getElementById('f6-start-btn').onclick = async () => {
                const school = document.getElementById('f6-school').value.trim();
                const major = document.getElementById('f6-major').value.trim();
                const type = document.getElementById('f6-type').value;
                if (!school) {
                    showToast('请输入目标学校', 'error');
                    return;
                }
                const btn = document.getElementById('f6-start-btn');
                btn.disabled = true;
                btn.textContent = 'AI 出题中...';
                const result = await this.start(school, major, type);
                if (result.success) {
                    this._renderQuestion();
                } else {
                    showToast('启动失败: ' + (result.error || '未知错误'), 'error');
                    btn.disabled = false;
                    btn.textContent = '🚀 开始面试';
                }
            };
        },

        _renderQuestion() {
            const body = document.getElementById('f6-mock-body');
            if (!body) return;
            const idx = this.state.questionIndex;
            const questions = this.state.current.questions;
            if (!questions || idx >= questions.length) {
                this._renderEvaluation();
                return;
            }
            body.innerHTML = `
                <div style="max-width:700px;margin:0 auto;">
                    <div style="background:linear-gradient(135deg,#eff6ff,#dbeafe);padding:20px;border-radius:12px;margin-bottom:20px;border-left:4px solid #3b82f6;">
                        <div style="font-size:13px;color:#6b7280;margin-bottom:8px;">问题 ${idx + 1} / ${questions.length}</div>
                        <div style="font-size:18px;font-weight:500;color:#1e3a8a;line-height:1.6;">${escapeHtml(questions[idx])}</div>
                    </div>
                    <div style="margin-bottom:12px;">
                        <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
                            <label style="font-size:13px;color:#374151;font-weight:500;">您的回答（建议英文）</label>
                            <span id="f6-char-count" style="font-size:12px;color:#6b7280;">0 字</span>
                        </div>
                        <textarea id="f6-answer" rows="10" placeholder="请用 STAR 法则组织您的回答：情境(Situation)-任务(Task)-行动(Action)-结果(Result)..." style="width:100%;padding:12px;border:1px solid #d1d5db;border-radius:8px;font-size:14px;line-height:1.6;box-sizing:border-box;font-family:inherit;resize:vertical;"></textarea>
                    </div>
                    <div style="display:flex;gap:8px;">
                        <button id="f6-quit-btn" style="padding:10px 16px;background:#f3f4f6;color:#374151;border:none;border-radius:6px;cursor:pointer;">放弃</button>
                        <button id="f6-next-btn" style="flex:1;padding:12px;background:linear-gradient(135deg,#3b82f6,#2563eb);color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:15px;font-weight:500;">
                            ${idx === questions.length - 1 ? '🎯 提交并查看评估' : '下一题 →'}
                        </button>
                    </div>
                </div>
            `;
            const textarea = document.getElementById('f6-answer');
            const charCount = document.getElementById('f6-char-count');
            textarea.oninput = () => { charCount.textContent = `${textarea.value.length} 字`; };
            document.getElementById('f6-quit-btn').onclick = () => {
                if (confirm('确定放弃本次面试？已答题目将不保存')) {
                    this._renderStart();
                }
            };
            document.getElementById('f6-next-btn').onclick = async () => {
                const answer = textarea.value.trim();
                if (!answer) {
                    showToast('请输入回答', 'error');
                    return;
                }
                if (answer.length < 20) {
                    if (!confirm('您的回答较短（少于20字），确定提交吗？')) return;
                }
                const btn = document.getElementById('f6-next-btn');
                btn.disabled = true;
                btn.textContent = '提交中...';
                const result = await this.submitAnswer(answer);
                btn.disabled = false;
                if (result.success) {
                    if (result.is_complete) {
                        this._renderEvaluation();
                    } else {
                        this._renderQuestion();
                    }
                } else {
                    showToast('提交失败: ' + (result.error || '未知错误'), 'error');
                    btn.textContent = idx === questions.length - 1 ? '🎯 提交并查看评估' : '下一题 →';
                }
            };
        },

        _renderEvaluation() {
            const body = document.getElementById('f6-mock-body');
            if (!body) return;
            const ev = this.state.evaluation || {};
            const scores = [
                { key: 'content', label: '内容质量', color: '#f59e0b', bg: '#fef3c7' },
                { key: 'logic', label: '逻辑清晰', color: '#3b82f6', bg: '#dbeafe' },
                { key: 'english', label: '英语表达', color: '#10b981', bg: '#d1fae5' },
                { key: 'depth', label: '专业深度', color: '#ec4899', bg: '#fce7f3' },
            ];
            const total = scores.reduce((sum, s) => sum + (ev[s.key] || 0), 0);
            const avg = (total / 4).toFixed(1);

            body.innerHTML = `
                <div style="max-width:700px;margin:0 auto;">
                    <div style="text-align:center;padding:20px 0;">
                        <div style="font-size:48px;">🎉</div>
                        <h3 style="margin:8px 0;">面试完成！</h3>
                        <div style="font-size:48px;font-weight:bold;color:#3b82f6;margin-top:8px;">${avg}<span style="font-size:24px;color:#6b7280;">/10</span></div>
                        <p style="color:#6b7280;font-size:13px;">综合评分</p>
                    </div>
                    <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-top:24px;">
                        ${scores.map(s => `
                            <div style="background:${s.bg};padding:16px;border-radius:8px;text-align:center;">
                                <div style="font-size:12px;color:#6b7280;">${s.label}</div>
                                <div style="font-size:32px;font-weight:bold;color:${s.color};">${ev[s.key] || '-'}<span style="font-size:14px;color:#6b7280;">/10</span></div>
                            </div>
                        `).join('')}
                    </div>
                    <div style="margin-top:24px;background:#f9fafb;padding:16px;border-radius:8px;border-left:4px solid #3b82f6;">
                        <h4 style="margin:0 0 8px;color:#1f2937;">💡 改进建议</h4>
                        <p style="margin:0;color:#374151;line-height:1.6;">${escapeHtml(ev.suggestion || '继续保持，多加练习！')}</p>
                    </div>
                    <div style="display:flex;gap:8px;margin-top:24px;">
                        <button id="f6-restart-btn" style="flex:1;padding:12px;background:linear-gradient(135deg,#10b981,#059669);color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:15px;">🔄 再来一次</button>
                        <button id="f6-history-btn2" style="flex:1;padding:12px;background:#a855f7;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:15px;">📜 查看历史</button>
                    </div>
                </div>
            `;
            document.getElementById('f6-restart-btn').onclick = () => this._renderStart();
            document.getElementById('f6-history-btn2').onclick = () => this._renderHistory();
        },

        async _renderHistory() {
            const body = document.getElementById('f6-mock-body');
            if (!body) return;
            body.innerHTML = '<div style="text-align:center;padding:40px;color:#6b7280;">加载中...</div>';
            await this.loadHistory();
            const list = this.state.history;
            if (!list || list.length === 0) {
                body.innerHTML = `
                    <div style="text-align:center;padding:60px;color:#9ca3af;">
                        <div style="font-size:48px;">📜</div>
                        <p>暂无面试历史</p>
                        <button id="f6-back-start" style="margin-top:16px;padding:8px 16px;background:#3b82f6;color:#fff;border:none;border-radius:6px;cursor:pointer;">开始第一次面试</button>
                    </div>
                `;
                document.getElementById('f6-back-start').onclick = () => this._renderStart();
                return;
            }
            body.innerHTML = `
                <div style="max-width:700px;margin:0 auto;">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
                        <h3 style="margin:0;">📜 面试历史 (${list.length})</h3>
                        <button id="f6-back-start" style="padding:6px 12px;background:#3b82f6;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:12px;">+ 新面试</button>
                    </div>
                    <div style="display:grid;gap:12px;">
                        ${list.map(item => {
                            const s = item.scores || {};
                            const total = ((s.content || 0) + (s.logic || 0) + (s.english || 0) + (s.depth || 0)) / 4;
                            const statusMap = { ongoing: { label: '进行中', color: '#f59e0b' }, completed: { label: '已完成', color: '#10b981' } };
                            const status = statusMap[item.status] || statusMap.ongoing;
                            return `
                                <div style="background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:14px;">
                                    <div style="display:flex;justify-content:space-between;align-items:start;">
                                        <div style="flex:1;">
                                            <div style="font-weight:600;font-size:15px;margin-bottom:4px;">
                                                🎓 ${escapeHtml(item.school_name)}
                                                ${item.major ? `<span style="font-weight:normal;color:#6b7280;font-size:13px;"> · ${escapeHtml(item.major)}</span>` : ''}
                                            </div>
                                            <div style="font-size:12px;color:#6b7280;">
                                                ${item.interview_type} · ${item.created_at ? new Date(item.created_at).toLocaleString('zh-CN') : ''}
                                            </div>
                                        </div>
                                        <div style="text-align:right;">
                                            <div style="font-size:24px;font-weight:bold;color:#3b82f6;">${total ? total.toFixed(1) : '-'}</div>
                                            <span style="background:${status.color};color:#fff;padding:2px 8px;border-radius:10px;font-size:11px;">${status.label}</span>
                                        </div>
                                    </div>
                                </div>
                            `;
                        }).join('')}
                    </div>
                </div>
            `;
            document.getElementById('f6-back-start').onclick = () => this._renderStart();
        },

        callable: {
            startMockInterview: {
                description: '开始一次模拟面试（弹出面试界面）',
                parameters: {},
                execute: function() {
                    MockInterview.show();
                    return { success: true, message: '模拟面试已打开' };
                },
            },
            showInterviewHistory: {
                description: '查看模拟面试历史记录',
                parameters: {},
                execute: async function() {
                    await MockInterview.loadHistory();
                    return { success: true, count: MockInterview.state.history.length, data: MockInterview.state.history };
                },
            },
        },
    };

    // ============================
    // 注册到全局
    // ============================
    window.P0Modules.ApplicationTimeline = ApplicationTimeline;
    window.P0Modules.ApplicationDashboard = ApplicationDashboard;
    window.P0Modules.KnowledgeRecommendation = KnowledgeRecommendation;
    window.P0Modules.QuestionTemplate = QuestionTemplate;
    window.P0Modules.MessageClassifier = MessageClassifier;
    window.P0Modules.MockInterview = MockInterview;

    // AI 可调用函数注册
    Object.entries({
        addApplication: ApplicationTimeline.callable.addApplication,
        showApplicationTimeline: ApplicationTimeline.callable.showApplicationTimeline,
        showDashboard: ApplicationDashboard.callable.showDashboard,
        exportApplicationICal: ApplicationDashboard.callable.exportICal,
        showFavorites: KnowledgeRecommendation.callable.showFavorites,
        searchFavorites: KnowledgeRecommendation.callable.searchFavorites,
        showQuestionTemplates: QuestionTemplate.callable.showQuestionTemplates,
        suggestTemplateQuestions: KnowledgeRecommendation.callable.suggestTemplateQuestions,
        classifyMessage: MessageClassifier.callable.classifyMessage,
        classifyMessages: MessageClassifier.callable.classifyMessages,
        startMockInterview: MockInterview.callable.startMockInterview,
        showInterviewHistory: MockInterview.callable.showInterviewHistory,
    }).forEach(([name, def]) => {
        window.__aiCallableFunctions[name] = {
            name,
            description: def.description,
            parameters: def.parameters || {},
            execute: def.execute,
        };
    });

    // 同时给 P0 兼容别名 add_application
    window.__aiCallableFunctions['add_application'] = {
        name: 'add_application',
        description: '添加用户的申请目标到时间线（兼容旧函数名）',
        parameters: ApplicationTimeline.callable.addApplication.parameters,
        execute: ApplicationTimeline.callable.addApplication.execute,
    };

    console.log('[P0-V2] 6个新业务功能模块已加载', {
        modules: ['ApplicationTimeline', 'ApplicationDashboard', 'KnowledgeRecommendation', 'QuestionTemplate', 'MessageClassifier', 'MockInterview'],
        aiFunctions: Object.keys(window.__aiCallableFunctions).length,
    });
})();
