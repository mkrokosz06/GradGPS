import { Tabs } from "expo-router";

/**
 * Tabs layout with the tab bar hidden — navigation is handled by the
 * hamburger menu in NavHeader. Keeping Tabs (not Stack) here is
 * important: it registers all sibling screens so router.navigate()
 * can switch between them without a push/pop stack.
 */
export default function Layout() {
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarStyle: { display: "none" },
      }}
    >
      <Tabs.Screen name="index"    options={{ title: "Home" }} />
      <Tabs.Screen name="timeline" options={{ title: "Timeline" }} />
      <Tabs.Screen name="upload"   options={{ title: "Upload" }} />
      <Tabs.Screen name="major"    options={{ title: "Major" }} />
      <Tabs.Screen name="account"  options={{ title: "Account" }} />
    </Tabs>
  );
}
