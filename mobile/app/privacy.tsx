import React from "react";
import { View, Text, ScrollView, TouchableOpacity, StyleSheet } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";

export default function PrivacyPolicyScreen() {
  const router = useRouter();

  return (
    <SafeAreaView style={styles.container} edges={["top", "left", "right"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}>
          <Text style={styles.back}>← Back</Text>
        </TouchableOpacity>
        <Text style={styles.title}>Privacy Policy</Text>
      </View>

      <ScrollView contentContainerStyle={styles.body} showsVerticalScrollIndicator={false}>
        <Text style={styles.updated}>Last updated: September 21, 2026</Text>

        <Section title="1. Who We Are">
          GradGPS is an independent planning tool operated by Matthew Krokosz, an individual developer based in the United States (the "we," "us," or "operator" referred to in this policy). You can reach us at support@gradgps.com or through the Contact Support screen in the app.{"\n\n"}
          GradGPS is a student-built tool and is not affiliated with, endorsed by, or sponsored by The Pennsylvania State University. It is not official academic advising. Course and program information comes from publicly available university sources, and "Penn State" and related names are the property of their respective owners.
        </Section>

        <Section title="2. What We Collect">
          When you use GradGPS, we collect:{"\n\n"}
          • Your name and email address, provided by your sign-in method (Google, Apple, or email verification code), and a user identifier created at sign-up{"\n"}
          • Your selected major and subplan, and any minors or certificates you declare{"\n"}
          • Basic account activity information: when you signed up, the date you last used the app, and the app version you are running{"\n"}
          • Academic data parsed from your uploaded transcript: course codes, grades, credits earned, and enrollment terms{"\n"}
          • A copy of the transcript PDF you upload, and — if you upload an official transcript — the date you acknowledged and consented to using it{"\n"}
          • Planning choices you make in the app: the classes you pick for a future slot, and any course substitution you tell us your adviser approved{"\n"}
          • Anything you write to us in the support form, along with the email address you give there{"\n\n"}
          We recommend uploading your unofficial transcript. An official transcript PDF may also carry your name and Penn State student ID number as printed on the document. We only extract and use the academic data listed above. We never ask you for, and never store, your account password, your Social Security Number, or any financial information. Your device's IP address is used momentarily to rate-limit sign-in codes and support messages; it is not written to our database and not linked to your account.
        </Section>

        <Section title="3. How We Use Your Information">
          Your data is used exclusively to:{"\n\n"}
          • Generate your personalized degree audit and academic timeline{"\n"}
          • Show your credit progress toward graduation{"\n"}
          • Recommend future courses based on your remaining requirements{"\n"}
          • Sign you in and keep your account secure{"\n"}
          • Respond when you contact support{"\n"}
          • Review anonymized, aggregate counts (such as total sign-ups, or how many people are on each app build) to improve GradGPS{"\n\n"}
          We do not sell or rent your personal information, and we do not share it with third parties for advertising or marketing. GradGPS uses no third-party analytics, advertising, or cross-site tracking services — there is no analytics SDK of any kind in the app, so there is nothing measuring you in the background.{"\n\n"}
          GradGPS builds your audit and timeline through our own matching against published university requirements. We do not send your personal data to third-party AI services, and we never use your data to train AI models.
        </Section>

        <Section title="4. Third-Party Services">
          GradGPS uses the following external services:{"\n\n"}
          • Sign-In Providers — If you sign in with Google or Apple, they handle authentication and share your name and email address with us. Their own privacy policies apply to your use of those services.{"\n"}
          • Email Delivery — We use Amazon Web Services to send emails such as sign-in verification codes and replies to your support requests.{"\n"}
          • University Course Bulletins — We fetch public course descriptions using the course code only.{"\n\n"}
          No personally identifiable information is sent to the course-bulletin service. As GradGPS expands to support additional schools, new institution-specific integrations may be added. Any such additions will be reflected in an updated Privacy Policy.
        </Section>

        <Section title="5. Data Storage">
          Your profile and transcript data are stored securely in cloud databases (AWS DynamoDB). Uploaded transcript PDF files — whether unofficial or official — are stored in encrypted object storage (AWS S3). Access is restricted to the GradGPS application. Deleting your transcript in the app removes the stored PDF and its parsed course data.
        </Section>

        <Section title="6. Data Retention">
          We retain your data while your account is active. If you do not use GradGPS for 24 consecutive months, we may delete your account and its associated data. You can permanently delete your account and all associated data at any time from the Account screen in the app — this removes your stored transcript PDF, your parsed course data, your saved planning choices and course substitutions, your profile record, and your active sessions. You may also request deletion by contacting us.
        </Section>

        <Section title="7. Your Rights & Choices">
          You can, at any time:{"\n\n"}
          • Access the profile and academic data we hold, viewable directly in the app{"\n"}
          • Correct or update your major, subplan, and in-progress classes in the app, or re-upload a transcript{"\n"}
          • Delete your transcript, or your entire account and all associated data, from the Account screen{"\n"}
          • Request a copy of your data, or ask us any privacy question, by contacting us{"\n\n"}
          We do not sell your personal information and have not done so. Because GradGPS does not track you across other websites or over time, we do not respond differently to browser "Do Not Track" signals.
        </Section>

        <Section title="8. State Privacy Rights">
          Some states — California, Colorado, Connecticut, Virginia, Texas and a growing list of others — give residents specific rights over their personal information. We extend the rights below to everyone who uses GradGPS, wherever you live, because it would be strange to run two different policies.{"\n\n"}
          What we collect, by category. In the language California uses:{"\n\n"}
          • Identifiers — your name, email address, and the account identifier created at sign-up. Collected from you and from your sign-in provider (Google or Apple). Kept while your account is active.{"\n"}
          • Education information — your uploaded transcript PDF and the course codes, grades, credits, and terms parsed from it; your major, subplan, and declared minors or certificates; the planning choices and course substitutions you make in the app. Collected from you. Kept while your account is active.{"\n"}
          • Internet or device activity — the date you last used the app and the app version you are running. Collected automatically from the app. Kept while your account is active.{"\n"}
          • Sensitive personal information — if you choose to upload an official transcript, the PDF carries your Penn State student ID number as printed on it. We don't extract or use that number; it simply sits inside the file you uploaded, which you can delete. We recommend the unofficial transcript for exactly this reason. We do not use or disclose sensitive personal information for any purpose other than providing the Service, so there is nothing for you to limit.{"\n\n"}
          We do not collect biometric information, precise geolocation, commercial or purchase records, or information about your race, religion, health, immigration status, union membership, sexual orientation, or the contents of your private messages.{"\n\n"}
          We do not sell or share your personal information. We have not sold personal information, and we have not shared it for cross-context behavioral advertising, in the preceding 12 months or ever. We do not do this for anyone, including users under 16. Because there is nothing to opt out of, we do not offer a "Do Not Sell or Share My Personal Information" link — the honest version of that link is this paragraph. We disclose personal information only to the service providers named in Section 4, who process it on our behalf under their own contracts and may not use it for their own purposes.{"\n\n"}
          Your rights:{"\n\n"}
          • Know and access — what we collect, why, where it came from, who we disclose it to, and a copy of the specific pieces we hold about you.{"\n"}
          • Delete — ask us to delete the personal information we hold about you.{"\n"}
          • Correct — ask us to fix inaccurate personal information.{"\n"}
          • Portability — get your data in a portable, readily usable format.{"\n"}
          • Opt out of sale or sharing — not applicable, because we do neither.{"\n"}
          • Limit the use of sensitive personal information — not applicable, because we only use it to provide the Service.{"\n"}
          • No retaliation — we will never deny you the Service, charge you a different price, or give you a worse experience for exercising any of these rights.{"\n\n"}
          How to exercise them. The fastest route is the app itself: the Account screen lets you view your data, correct your major and classes, delete your transcript, and permanently delete your entire account — no request, no waiting. Otherwise, email support@gradgps.com or use the Contact Support screen and say what you want. To protect your account we will ask you to make the request from the email address associated with it, or to confirm details only the account holder would know; we'll use what you send us only to handle the request. We aim to respond within 45 days and will tell you if we need the extension the law allows. If we have to decline, we'll explain why. You may use an authorized agent, who must provide written permission from you and verify their own identity.{"\n\n"}
          If you are in a state whose law gives you a right to appeal a decision we make about your request, email us with "Privacy Appeal" in the subject line and a person — not an automated process — will review it and write back with the outcome and the reasons.
        </Section>

        <Section title="9. Security">
          We take reasonable measures to protect your data, including encrypted storage and access controls. However, no system is completely secure. Please keep the sign-in method associated with your account (your Google, Apple, or email account) secure and do not share it with others.
        </Section>

        <Section title="10. Age Requirement & Children's Privacy">
          GradGPS is intended for current and prospective college students. You must be at least 13 years old to create an account or use the Service, and if you are under 18 you may use it only with the consent of a parent or guardian. The Service is not directed at children.{"\n\n"}
          We do not knowingly collect personal information from anyone under 13. If we learn that we have, we delete the account and its data. If you are a parent or guardian and believe a child under 13 has given us data, contact us at support@gradgps.com and we will delete it.
        </Section>

        <Section title="11. Changes to This Policy">
          We may update this Privacy Policy from time to time. We will notify you of material changes through the app. Continued use after changes are posted means you accept the updated policy.
        </Section>

        <Section title="12. Contact Us">
          If you have questions or want to request data deletion, contact us at support@gradgps.com or through the Contact Support screen in the app.
        </Section>
      </ScrollView>
    </SafeAreaView>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={{ marginBottom: 24 }}>
      <Text style={styles.sectionTitle}>{title}</Text>
      <Text style={styles.sectionBody}>{children}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#ffffff" },
  header: {
    paddingHorizontal: 20, paddingTop: 16, paddingBottom: 14,
    borderBottomWidth: 1, borderBottomColor: "#f1f5f9",
  },
  back:  { color: "#2a5298", fontSize: 14, marginBottom: 10 },
  title: { color: "#1a3a6b", fontSize: 22, fontWeight: "700" },
  body:  { paddingHorizontal: 24, paddingTop: 20, paddingBottom: 60 },
  updated: { color: "#94a3b8", fontSize: 12, marginBottom: 28 },
  sectionTitle: { color: "#1e293b", fontSize: 15, fontWeight: "700", marginBottom: 6 },
  sectionBody:  { color: "#475569", fontSize: 14, lineHeight: 22 },
});
