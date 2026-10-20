import SwiftUI

struct RootView: View {
    @State private var address = ServerSettings.urlString
    @State private var failure: String?
    @State private var loading = true
    @State private var reloadToken = 0
    @State private var showSettings = false

    private let background = Color(red: 0.09, green: 0.09, blue: 0.09)
    private let orange = Color(red: 1.0, green: 0.6, blue: 0.4)

    var body: some View {
        ZStack {
            background.ignoresSafeArea()

            if let url = URL(string: address) {
                WebView(url: url, reloadToken: reloadToken, failure: $failure, loading: $loading)
                    .ignoresSafeArea()
                    .opacity(failure == nil ? 1 : 0)
            }

            if let failure {
                ProblemView(message: failure, address: address,
                            retry: { self.failure = nil; reloadToken += 1 },
                            change: { showSettings = true })
            } else if loading {
                ProgressView().tint(orange).scaleEffect(1.3)
            }
        }
        .sheet(isPresented: $showSettings) {
            SettingsView(address: $address) { reloadToken += 1; failure = nil }
        }
    }
}

private struct ProblemView: View {
    let message: String
    let address: String
    let retry: () -> Void
    let change: () -> Void
    private let orange = Color(red: 1.0, green: 0.6, blue: 0.4)

    var body: some View {
        VStack(spacing: 18) {
            Image(systemName: "wifi.exclamationmark")
                .font(.system(size: 44)).foregroundStyle(orange)
            Text("Keine Verbindung").font(.title2.bold()).foregroundStyle(.white)
            Text(message).multilineTextAlignment(.center).foregroundStyle(.white.opacity(0.75))
            Text(address).font(.footnote.monospaced()).foregroundStyle(.white.opacity(0.5))
            HStack(spacing: 12) {
                Button("Erneut versuchen", action: retry).buttonStyle(.borderedProminent).tint(orange).foregroundStyle(.black)
                Button("Adresse ändern", action: change).buttonStyle(.bordered).tint(orange)
            }
        }
        .padding(28)
    }
}

private struct SettingsView: View {
    @Binding var address: String
    let applied: () -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var draft = ""

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("http://192.168.0.3:8008", text: $draft)
                        .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                } header: {
                    Text("Server-Adresse")
                } footer: {
                    Text("Die Adresse deiner CrateMind-Webapp im Heimnetz. Unterwegs brauchst du ein VPN dorthin.")
                }
                if !draft.isEmpty && !ServerSettings.isValid(draft) {
                    Text("Das ist keine gültige Adresse.").foregroundStyle(.red)
                }
            }
            .navigationTitle("Verbindung")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Abbrechen") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Speichern") {
                        ServerSettings.urlString = draft
                        address = ServerSettings.urlString
                        applied()
                        dismiss()
                    }.disabled(!ServerSettings.isValid(draft))
                }
            }
        }
        .onAppear { draft = address }
        .presentationDetents([.medium])
    }
}
