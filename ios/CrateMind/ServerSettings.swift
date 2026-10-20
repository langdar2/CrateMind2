import Foundation

/// Where the CrateMind web app lives. Kept in UserDefaults so it survives updates.
enum ServerSettings {
    static let key = "server_url"
    static let fallback = "http://192.168.0.3:8008"

    static var urlString: String {
        get { UserDefaults.standard.string(forKey: key) ?? fallback }
        set { UserDefaults.standard.set(normalise(newValue), forKey: key) }
    }

    static var url: URL? { URL(string: urlString) }

    /// "192.168.0.3:8008" -> "http://192.168.0.3:8008"; trailing slashes dropped.
    static func normalise(_ raw: String) -> String {
        var text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.isEmpty { return fallback }
        if !text.contains("://") { text = "http://" + text }
        while text.hasSuffix("/") { text.removeLast() }
        return text
    }

    static func isValid(_ raw: String) -> Bool {
        guard let url = URL(string: normalise(raw)), let host = url.host else { return false }
        return !host.isEmpty && (url.scheme == "http" || url.scheme == "https")
    }
}
