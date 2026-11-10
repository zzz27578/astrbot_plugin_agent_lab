import { Component, type ErrorInfo, type ReactNode } from "react";

/** Keep rendering failures visible even before the first API request. */
export class StartupBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[Agent Lab] 页面渲染失败", error, info.componentStack);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <main
        role="alert"
        style={{ padding: 32, maxWidth: 720, margin: "0 auto" }}
      >
        <h1>Agent Lab 页面加载失败</h1>
        <p>前端发生了错误，任务没有因此重新执行。</p>
        <p>
          请关闭此插件页面再重新打开。若仍失败，可在浏览器控制台查看具体前端错误。
        </p>
        <button onClick={() => window.location.reload()}>重新加载此页面</button>
      </main>
    );
  }
}
