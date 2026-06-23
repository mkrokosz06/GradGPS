import { Tabs } from "expo-router";
import { View, Text } from "react-native";

function TabIcon({ label, color }: { label: string; color: string }) {
  const icons: Record<string, string> = {
    Audit: "🎓",
    Upload: "📄",
    Major: "🔍",
  };
  return (
    <View className="items-center">
      <Text style={{ fontSize: 20 }}>{icons[label] ?? "●"}</Text>
      <Text style={{ fontSize: 10, color }}>{label}</Text>
    </View>
  );
}

export default function TabLayout() {
  return (
    <Tabs
      screenOptions={{
        tabBarActiveTintColor: "#E8C84B",
        tabBarInactiveTintColor: "#94a3b8",
        tabBarStyle: { backgroundColor: "#1a3a6b", borderTopWidth: 0 },
        headerShown: false,
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: "Audit",
          tabBarIcon: ({ color }) => <TabIcon label="Audit" color={color} />,
          tabBarLabel: () => null,
        }}
      />
      <Tabs.Screen
        name="upload"
        options={{
          title: "Upload",
          tabBarIcon: ({ color }) => <TabIcon label="Upload" color={color} />,
          tabBarLabel: () => null,
        }}
      />
      <Tabs.Screen
        name="major"
        options={{
          title: "Major",
          tabBarIcon: ({ color }) => <TabIcon label="Major" color={color} />,
          tabBarLabel: () => null,
        }}
      />
    </Tabs>
  );
}
