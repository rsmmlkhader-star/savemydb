import { Tabs } from 'expo-router';

export default function TabLayout() {
  return (
    <Tabs screenOptions={{ headerShown: false, tabBarStyle: { backgroundColor: '#0f172a' }, tabBarActiveTintColor: '#60a5fa' }}>
      <Tabs.Screen name="index" options={{ title: 'SaveMyDB' }} />
    </Tabs>
  );
}