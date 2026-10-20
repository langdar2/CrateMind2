import SwiftUI
import WebKit

/// The CrateMind web app, full screen, behaving like part of the app rather than a browser page.
struct WebView: UIViewRepresentable {
    let url: URL
    let reloadToken: Int
    @Binding var failure: String?
    @Binding var loading: Bool

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.allowsInlineMediaPlayback = true
        config.mediaTypesRequiringUserActionForPlayback = []      // the player starts the next track by itself
        config.allowsPictureInPictureMediaPlayback = false

        let view = WKWebView(frame: .zero, configuration: config)
        view.navigationDelegate = context.coordinator
        view.allowsBackForwardNavigationGestures = true
        view.isOpaque = false
        view.backgroundColor = UIColor(red: 0.09, green: 0.09, blue: 0.09, alpha: 1)
        view.scrollView.backgroundColor = view.backgroundColor
        view.scrollView.contentInsetAdjustmentBehavior = .never   // the page handles the safe areas itself
        view.scrollView.bounces = true
        view.customUserAgent = nil

        let refresh = UIRefreshControl()
        refresh.addTarget(context.coordinator, action: #selector(Coordinator.pulled(_:)), for: .valueChanged)
        view.scrollView.refreshControl = refresh

        context.coordinator.webView = view
        view.load(URLRequest(url: url))
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) {
        let coordinator = context.coordinator
        coordinator.parent = self
        // New address or an explicit retry: load again.
        if coordinator.loadedURL != url || coordinator.reloadToken != reloadToken {
            coordinator.loadedURL = url
            coordinator.reloadToken = reloadToken
            view.load(URLRequest(url: url))
        }
    }

    final class Coordinator: NSObject, WKNavigationDelegate {
        var parent: WebView
        weak var webView: WKWebView?
        var loadedURL: URL?
        var reloadToken: Int

        init(_ parent: WebView) {
            self.parent = parent
            self.loadedURL = parent.url
            self.reloadToken = parent.reloadToken
        }

        @objc func pulled(_ control: UIRefreshControl) {
            webView?.reload()
            control.endRefreshing()
        }

        func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
            DispatchQueue.main.async { self.parent.loading = true }
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            DispatchQueue.main.async {
                self.parent.loading = false
                self.parent.failure = nil
            }
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            report(error)
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            report(error)
        }

        private func report(_ error: Error) {
            let code = (error as NSError).code
            if code == NSURLErrorCancelled { return }              // a newer navigation replaced this one
            DispatchQueue.main.async {
                self.parent.loading = false
                self.parent.failure = Self.explain(error as NSError)
            }
        }

        static func explain(_ error: NSError) -> String {
            switch error.code {
            case NSURLErrorNotConnectedToInternet: return "Kein Netzwerk. Bist du mit dem WLAN verbunden?"
            case NSURLErrorTimedOut: return "Der Server antwortet nicht. Läuft er, und bist du im Heimnetz?"
            case NSURLErrorCannotFindHost, NSURLErrorCannotConnectToHost:
                return "Der Server ist nicht erreichbar. Stimmt die Adresse, und bist du im Heimnetz?"
            default: return error.localizedDescription
            }
        }

        // Links to other sites open in Safari instead of replacing the app.
        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            if action.navigationType == .linkActivated, let target = action.request.url,
               let host = target.host, host != parent.url.host {
                UIApplication.shared.open(target)
                decisionHandler(.cancel)
                return
            }
            decisionHandler(.allow)
        }
    }
}
