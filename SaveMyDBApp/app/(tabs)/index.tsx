import { useState, useEffect } from 'react';
import { ScrollView, StyleSheet, Text, TouchableOpacity, View, TextInput, ActivityIndicator } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';

const API = 'https://savemydb-w5gi.onrender.com';

export default function HomeScreen() {
  const [screen, setScreen] = useState<'login' | 'home'>('login');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [token, setToken] = useState('');
  const [status, setStatus] = useState('Ready to sync!');
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState('');
  const [connections, setConnections] = useState<any[]>([]);

  // Check if already logged in
  useEffect(() => {
    AsyncStorage.getItem('token').then(t => {
      if (t) { setToken(t); setScreen('home'); fetchConnections(t); }
    });
  }, []);

  const fetchConnections = async (t: string) => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/connections`, {
        headers: { Authorization: `Bearer ${t}` }
      });
      const data = await res.json();
      if (data.status === 'ok') setConnections(data.data || []);
    } catch {
      setStatus('⚠️ Could not reach server');
    }
    setLoading(false);
  };

  const handleLogin = async () => {
    if (!username || !password) { setError('Enter username and password'); return; }
    setLoading(true); setError('');
    try {
      const res = await fetch(`${API}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
      });
      const data = await res.json();
      if (data.status === 'ok') {
        await AsyncStorage.setItem('token', data.data.token);
        setToken(data.data.token);
        setScreen('home');
        fetchConnections(data.data.token);
      } else {
        setError(data.message || 'Login failed');
      }
    } catch {
      setError('Cannot connect to server');
    }
    setLoading(false);
  };

  const handleSync = async () => {
    setSyncing(true);
    setStatus('Syncing...');
    try {
      const res = await fetch(`${API}/api/health`);
      const data = await res.json();
      if (data.status === 'ok') {
        setStatus('✅ Server alive! Ready to sync.');
      }
    } catch {
      setStatus('⚠️ Server unreachable');
    }
    setSyncing(false);
  };

  const handleLogout = async () => {
    await AsyncStorage.removeItem('token');
    setToken(''); setScreen('login');
    setUsername(''); setPassword('');
    setConnections([]);
  };

  // ── Login Screen ──────────────────────────
  if (screen === 'login') {
    return (
      <ScrollView style={styles.container}>
        <View style={styles.header}>
          <Text style={styles.title}>💾 SaveMyDB</Text>
          <Text style={styles.subtitle}>Sign in to continue</Text>
        </View>
        <View style={styles.card}>
          {error ? <Text style={styles.errorText}>{error}</Text> : null}
          <Text style={styles.label}>Username</Text>
          <TextInput
            style={styles.input}
            value={username}
            onChangeText={setUsername}
            placeholder="your username"
            placeholderTextColor="#64748b"
            autoCapitalize="none"
          />
          <Text style={styles.label}>Password</Text>
          <TextInput
            style={styles.input}
            value={password}
            onChangeText={setPassword}
            placeholder="your password"
            placeholderTextColor="#64748b"
            secureTextEntry
          />
          <TouchableOpacity style={styles.syncButton} onPress={handleLogin} disabled={loading}>
            {loading
              ? <ActivityIndicator color="white" />
              : <Text style={styles.syncButtonText}>Login</Text>}
          </TouchableOpacity>
        </View>
      </ScrollView>
    );
  }

  // ── Home Screen ───────────────────────────
  return (
    <ScrollView style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>💾 SaveMyDB</Text>
        <Text style={styles.subtitle}>Google Sheets ↔ MySQL Sync</Text>
      </View>

      <View style={styles.statusBox}>
        <Text style={styles.statusText}>{status}</Text>
      </View>

      <TouchableOpacity style={styles.syncButton} onPress={handleSync} disabled={syncing}>
        {syncing
          ? <ActivityIndicator color="white" />
          : <Text style={styles.syncButtonText}>🔄 Sync Now</Text>}
      </TouchableOpacity>

      <Text style={styles.tableTitle}>🔌 Active Connections</Text>
      {loading
        ? <ActivityIndicator color="#60a5fa" style={{ margin: 20 }} />
        : connections.length === 0
          ? <View style={styles.row}><Text style={styles.rowName}>No connections yet</Text></View>
          : connections.map((c, i) => (
              <View key={i} style={styles.row}>
                <Text style={styles.rowName}>{c.connection_id}</Text>
                <Text style={styles.rowPrice}>{c.db_type}</Text>
              </View>
            ))
      }

      <TouchableOpacity style={styles.logoutButton} onPress={handleLogout}>
        <Text style={styles.logoutText}>Logout</Text>
      </TouchableOpacity>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0f172a' },
  header: { padding: 30, paddingTop: 60, alignItems: 'center' },
  title: { fontSize: 32, fontWeight: 'bold', color: '#60a5fa' },
  subtitle: { fontSize: 14, color: '#94a3b8', marginTop: 5 },
  card: { margin: 20, padding: 20, backgroundColor: '#1e293b', borderRadius: 12 },
  label: { color: '#94a3b8', fontSize: 13, marginBottom: 6, marginTop: 12 },
  input: { backgroundColor: '#0f172a', color: '#e2e8f0', padding: 12, borderRadius: 8, fontSize: 15, borderWidth: 1, borderColor: '#334155' },
  errorText: { color: '#f87171', textAlign: 'center', marginBottom: 10 },
  statusBox: { margin: 20, padding: 15, backgroundColor: '#1e293b', borderRadius: 10 },
  statusText: { color: '#94a3b8', textAlign: 'center', fontSize: 14 },
  syncButton: { margin: 20, padding: 18, backgroundColor: '#3b82f6', borderRadius: 12, alignItems: 'center' },
  syncButtonText: { color: 'white', fontSize: 18, fontWeight: 'bold' },
  tableTitle: { color: '#e2e8f0', fontSize: 18, fontWeight: 'bold', marginLeft: 20, marginBottom: 10 },
  row: { margin: 10, marginTop: 5, padding: 15, backgroundColor: '#1e293b', borderRadius: 10 },
  rowName: { color: '#e2e8f0', fontSize: 15, fontWeight: '600' },
  rowPrice: { color: '#60a5fa', fontSize: 14, marginTop: 4 },
  logoutButton: { margin: 20, padding: 15, alignItems: 'center' },
  logoutText: { color: '#64748b', fontSize: 14 },
});