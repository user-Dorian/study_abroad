/**
 * 统一 API 客户端
 * 封装了认证、错误处理、重试机制、请求取消与拦截器
 *
 * 数据来源:
 *   - client/static/index.html  中的 apiRequest 函数（第3163-3190行）
 *   - consultant/static/index.html 中的 apiRequest 函数（第3085-3106行）
 *   - common/static/shared/p0-modules.js 中的 apiRequest 函数（第27-46行）
 *
 * 兼容性:
 *   - 同时兼容 client 端（rag-auth-token）和 consultant 端（consultant-auth-token）
 *   - 保留原有 apiRequest 的 401 重定向、JSON 错误解析行为
 */
class ApiClient {
  /**
   * @param {Object} options
   * @param {string}  options.baseURL        - API 基础路径（如 '/api'），默认 ''
   * @param {string}  options.tokenKey       - localStorage token 键名，默认 'rag-auth-token'
   * @param {string}  options.userKey        - localStorage 用户信息键名，默认 'rag-auth-user'
   * @param {string}  options.loginPath      - 未认证跳转路径，默认 '/login.html'
   * @param {number}  options.maxRetries     - 请求失败最大重试次数（0 表示不重试），默认 0
   * @param {number}  options.retryDelay     - 重试基础延迟（ms），默认 1000
   * @param {Function} options.onUnauthorized - 自定义 401 处理函数，默认清 token 并跳转
   */
  constructor(options = {}) {
    this.baseURL = options.baseURL || '';
    this.tokenKey = options.tokenKey || 'rag-auth-token';
    this.userKey = options.userKey || 'rag-auth-user';
    this.loginPath = options.loginPath || '/login.html';
    this.maxRetries = options.maxRetries || 0;
    this.retryDelay = options.retryDelay || 1000;

    // 自定义 401 回调（覆盖默认行为时使用）
    this._onUnauthorized = options.onUnauthorized || null;

    // 拦截器
    this._requestInterceptors = [];
    this._responseInterceptors = [];

    // AbortController 表（按 requestId 管理）
    this._abortControllers = new Map();
  }

  // ================================================================
  //  认证相关
  // ================================================================

  /** 获取当前 token（优先主键，降级兼容 consultant-auth-token / auth_token） */
  getToken() {
    return (
      localStorage.getItem(this.tokenKey) ||
      localStorage.getItem('consultant-auth-token') ||
      localStorage.getItem('auth_token') ||
      ''
    );
  }

  /** 获取当前用户信息（解析后的对象） */
  getUser() {
    try {
      const raw = localStorage.getItem(this.userKey);
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  }

  /** 清除所有认证信息 */
  clearToken() {
    localStorage.removeItem(this.tokenKey);
    localStorage.removeItem(this.userKey);
    // 兼容旧版键名
    localStorage.removeItem('consultant-auth-token');
    localStorage.removeItem('consultant-auth-user');
    localStorage.removeItem('auth_token');
  }

  // ================================================================
  //  拦截器
  // ================================================================

  /**
   * 注册请求拦截器
   * @param {Function} fn - (config) => config，config 包含 { method, headers, body, signal }
   * @returns {ApiClient} this
   */
  addRequestInterceptor(fn) {
    this._requestInterceptors.push(fn);
    return this;
  }

  /**
   * 注册响应拦截器
   * @param {Function} fn - (response, config) => response | Promise<response>
   * @returns {ApiClient} this
   */
  addResponseInterceptor(fn) {
    this._responseInterceptors.push(fn);
    return this;
  }

  // ================================================================
  //  内部方法
  // ================================================================

  /** 构建认证头 + 自定义头 */
  _buildHeaders(customHeaders = {}) {
    const headers = { 'Content-Type': 'application/json', ...customHeaders };
    const token = this.getToken();
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    return headers;
  }

  /** 处理 401 未认证响应 */
  _handleUnauthorized() {
    if (typeof this._onUnauthorized === 'function') {
      this._onUnauthorized();
      return;
    }
    // 默认行为：清 token 并跳转登录页
    this.clearToken();
    // 避免在登录页面上重复重定向
    if (!window.location.pathname.includes('/login.html')) {
      window.location.replace(this.loginPath);
    }
    throw new ApiClient.AuthError('未认证，请重新登录');
  }

  /** 解析错误响应体，提取 detail 信息 */
  async _parseErrorResponse(resp) {
    try {
      const ct = resp.headers.get('content-type') || '';
      if (ct.includes('application/json')) {
        const data = await resp.json();
        return data.detail || data.message || `HTTP ${resp.status}`;
      }
      const text = await resp.text();
      return text || `HTTP ${resp.status}: ${resp.statusText}`;
    } catch {
      return `HTTP ${resp.status}: ${resp.statusText}`;
    }
  }

  /** 串行执行拦截器链 */
  async _applyInterceptors(interceptors, input) {
    let result = input;
    for (const fn of interceptors) {
      result = await fn(result);
    }
    return result;
  }

  // ================================================================
  //  核心请求方法
  // ================================================================

  /**
   * 发起 API 请求
   * @param {string}  method          - HTTP 方法
   * @param {string}  path            - 请求路径（相对路径，会自动拼接 baseURL）
   * @param {Object}  [options]
   * @param {Object}  [options.body]  - 请求体（字符串），POST/PUT 时使用
   * @param {Object}  [options.headers] - 自定义请求头
   * @param {string}  [options.requestId] - 请求标识（用于取消）
   * @param {AbortSignal} [options.signal] - 外部 AbortSignal
   * @param {boolean} [options.rawResponse] - 为 true 时直接返回 Response 对象（不解析 JSON）
   * @returns {Promise<any>} 解析后的 JSON 数据，或 Response 对象
   */
  async request(method, path, options = {}) {
    const url = `${this.baseURL}${path}`;

    // --- 取消控制 ---
    let controller = null;
    let signal = options.signal || null;
    if (options.requestId) {
      // 取消同一 requestId 的上一次请求
      const prev = this._abortControllers.get(options.requestId);
      if (prev && !prev.signal.aborted) {
        prev.abort();
      }
      controller = new AbortController();
      this._abortControllers.set(options.requestId, controller);
      signal = controller.signal;
    }

    // --- 构建请求配置 ---
    let config = {
      method,
      headers: this._buildHeaders(options.headers),
      body: options.body || undefined,
      signal,
    };

    // 前置拦截器
    config = await this._applyInterceptors(this._requestInterceptors, config);

    // --- 发起请求（含重试） ---
    let lastError = null;

    for (let attempt = 0; attempt <= this.maxRetries; attempt++) {
      try {
        let resp = await fetch(url, config);

        // 响应拦截器
        resp = await this._applyInterceptors(this._responseInterceptors, resp);

        // 401 → 认证失效
        if (resp.status === 401) {
          this._handleUnauthorized();
          // _handleUnauthorized 会 throw，不会走到这里
        }

        // 原始 Response 模式（用于 SSE 流等场景）
        if (options.rawResponse) {
          return resp;
        }

        // SSE 流响应（text/event-stream）也直接返回原始 Response
        const contentType = resp.headers.get('content-type') || '';
        if (contentType.includes('text/event-stream')) {
          return resp;
        }

        // 解析 JSON 响应体
        const data = await resp.json();

        // 业务层错误码（非 2xx）
        if (!resp.ok) {
          const detail = (data && (data.detail || data.message)) || `HTTP错误: ${resp.status}`;
          throw new ApiClient.RequestError(detail, resp.status, data);
        }

        return data;
      } catch (err) {
        lastError = err;

        // AbortError 不重试，直接抛出
        if (err.name === 'AbortError') {
          throw err;
        }

        // AuthError（401 已处理）不重试
        if (err instanceof ApiClient.AuthError) {
          throw err;
        }

        // 已达最大重试次数，抛出最后一个错误
        if (attempt >= this.maxRetries) {
          throw err;
        }

        // 指数退避等待（1s, 2s, 4s, ...）
        const delay = this.retryDelay * Math.pow(2, attempt);
        await new Promise((resolve) => setTimeout(resolve, delay));
      }
    }

    // 理论上不会执行到这里，但防御性兜底
    throw lastError || new Error('未知请求错误');
  }

  // ================================================================
  //  便捷方法
  // ================================================================

  /** GET 请求 */
  get(path, options = {}) {
    return this.request('GET', path, options);
  }

  /** POST 请求（自动 JSON 序列化 body） */
  post(path, body, options = {}) {
    const bodyStr = body !== undefined ? JSON.stringify(body) : undefined;
    return this.request('POST', path, { ...options, body: bodyStr });
  }

  /** PUT 请求（自动 JSON 序列化 body） */
  put(path, body, options = {}) {
    const bodyStr = body !== undefined ? JSON.stringify(body) : undefined;
    return this.request('PUT', path, { ...options, body: bodyStr });
  }

  /** DELETE 请求 */
  delete(path, options = {}) {
    return this.request('DELETE', path, options);
  }

  // ================================================================
  //  请求取消
  // ================================================================

  /**
   * 取消指定 requestId 的请求
   * @param {string} requestId
   */
  cancel(requestId) {
    const controller = this._abortControllers.get(requestId);
    if (controller && !controller.signal.aborted) {
      controller.abort();
    }
    this._abortControllers.delete(requestId);
  }

  /** 取消全部进行中的请求 */
  cancelAll() {
    for (const [id, controller] of this._abortControllers) {
      if (!controller.signal.aborted) {
        controller.abort();
      }
    }
    this._abortControllers.clear();
  }

  // ================================================================
  //  工厂方法
  // ================================================================

  /**
   * 创建一个预配置的实例
   * @param {string} tokenKey - localStorage token 键名
   * @param {Object} extra    - 其他选项（同构造函数）
   * @returns {ApiClient}
   */
  static create(tokenKey, extra = {}) {
    return new ApiClient({ tokenKey, ...extra });
  }
}

// ================================================================
//  自定义错误类型
// ================================================================

/** 认证错误（401） */
ApiClient.AuthError = class AuthError extends Error {
  constructor(message) {
    super(message);
    this.name = 'AuthError';
  }
};

/** 请求错误（非 2xx 业务错误） */
ApiClient.RequestError = class RequestError extends Error {
  constructor(message, status, data) {
    super(message);
    this.name = 'RequestError';
    this.status = status;
    this.data = data;
  }
};

// ================================================================
//  全局默认实例（向后兼容）
// ================================================================

/**
 * 默认 API 客户端实例
 * - baseURL: 优先使用 window.API_BASE（由后端模板注入）
 * - 用法: window.api.get('/xxx') 或 window.api.post('/xxx', { ... })
 */
window.api = new ApiClient({
  baseURL: window.API_BASE || '',
});

// 暴露类本身，便于创建自定义实例
window.ApiClient = ApiClient;
