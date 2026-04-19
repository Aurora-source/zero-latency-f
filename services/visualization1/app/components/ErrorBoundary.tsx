import React from "react";

interface ErrorBoundaryState {
  hasError: boolean;
}

export default class ErrorBoundary extends React.Component<
  React.PropsWithChildren,
  ErrorBoundaryState
> {
  reloadTimer: number | null = null;

  constructor(props: React.PropsWithChildren) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("[ui] error boundary caught an application error", error, info);
    this.reloadTimer = window.setTimeout(() => {
      window.location.reload();
    }, 5000);
  }

  componentWillUnmount() {
    if (this.reloadTimer !== null) {
      window.clearTimeout(this.reloadTimer);
    }
  }

  handleReload = () => {
    window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex min-h-screen items-center justify-center bg-black px-6 text-white">
          <button
            type="button"
            onClick={this.handleReload}
            className="rounded-2xl border border-white/15 bg-white/10 px-6 py-4 text-left shadow-xl transition hover:bg-white/15"
          >
            <div className="text-lg font-semibold">Something went wrong.</div>
            <div className="mt-2 text-sm text-white/70">
              Click to reload. Automatic reload in 5 seconds.
            </div>
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
