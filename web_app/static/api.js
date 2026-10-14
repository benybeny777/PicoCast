// 画面通信の共通入口。変更操作だけに起動ごとのトークンを付ける。
(() => {
  const token = document.querySelector('meta[name="picocast-token"]').content;
  const nativeFetch = window.fetch.bind(window);
  window.fetch = (input, init) => {
    const url = new URL(input instanceof Request ? input.url : input, window.location.href);
    const method = String(init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
    if (url.origin !== window.location.origin || !['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
      return nativeFetch(input, init);
    }
    const request = new Request(input instanceof Request ? input : url.href, init);
    const headers = new Headers(request.headers);
    headers.set('X-PicoCast-Token', token);
    // 変更操作のリダイレクト先へトークンや本文を送らない。
    return nativeFetch(new Request(request, {headers, redirect: 'error'}));
  };
})();
