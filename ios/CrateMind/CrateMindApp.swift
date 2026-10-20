import SwiftUI
import AVFoundation

@main
struct CrateMindApp: App {
    init() {
        // Without the playback category iOS silences the web view's audio as soon as the
        // screen locks or the app goes to the background.
        try? AVAudioSession.sharedInstance().setCategory(.playback, mode: .default, options: [])
        try? AVAudioSession.sharedInstance().setActive(true)
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .preferredColorScheme(.dark)
        }
    }
}
