# 🚗 Infotainment Dashboard

A modern, responsive vehicle infotainment system interface. This repository features a React Native tablet application designed specifically for a landscape touch-screen experience.

---

## 🛠 Tech Stack

**Native Tablet Environment (`infotainment-native`):**
* **Framework:** React Native + Expo
* **Language:** TypeScript
* **Styling:** NativeWind (Tailwind for React Native)
* **Routing:** State-based view rendering (optimized for single-screen dashboard flow)

---

## 📂 Project Structure

The project separates the native mobile environment into its own directory to prevent dependency conflicts:

```text
infotainment/
├── app/                      # Legacy web components
├── infotainment-native/      # EXPO NATIVE APP - Active Development
├── styles/                   # Global CSS and Tailwind configurations
└── Guidelines.md             # Project guidelines and attributions

Running the Native Version (Tablet / Expo Go)
Important: You must navigate into the infotainment-native directory to run the app. Do not run installation commands in the root folder.

'''
# Navigate to the native app directory
cd infotainment-native

# Install native dependencies
npm install

# Start the Expo bundler (Clear cache is recommended on first run)
npx expo start -c
'''
Once the Metro bundler starts, scan the QR code with the Expo Go app on your tablet, or press a to run it on an Android Emulator.

📦 Building for Production
Android Tablet (APK via Expo EAS):
To generate a standalone .apk file that you can install directly onto an Android tablet, use Expo Application Services (EAS).

'''
cd infotainment-native
eas build -p android --profile preview
'''
(Note: This requires the EAS CLI to be installed globally npm install -g eas-cli and a free Expo account).

🗺️ Navigation Routing Logic

The navigation system treats the road network as a mathematical graph (nodes as intersections, edges as roads) to calculate optimal paths. Depending on the user's priority, the system utilizes different pathfinding algorithms under the hood:

1. Shortest Physical Route (Dijkstra’s Algorithm)
When the user requests the absolute shortest distance, the system ignores connection feasibility (number of turns, road types) and calculates the mathematical minimum distance using a weighted graph. 
* **Pros:** Guarantees the shortest possible driving distance.
* **Cons:** May route through residential side-streets or complex intersections just to save a few meters.

2. Most Connected / Fewest Turns (Breadth-First Search)
When the priority is a smooth driving experience, the system treats the map as an unweighted graph, calculating the route based on the fewest number of "hops" or road changes.
* **Pros:** Keeps the driver on major, highly connected arterial roads and highways.
* **Cons:** Physical driving distance may be noticeably longer.

3. Balanced & Direct (A* Search)
The default routing method for the dashboard. A* (A-Star) combines actual distance traveled (like Dijkstra) with a directional heuristic (an educated guess of the remaining distance to the destination). 
* **Pros:** Mimics human logic by aggressively stretching *towards* the destination, balancing the shortest physical path with the most direct trajectory.