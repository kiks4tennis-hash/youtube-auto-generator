-- 開発・動作確認用の初期フレーズ（本番はGemini APIが自動生成する）
INSERT INTO phrases (phrase, example, scene, topic) VALUES
('Could you give me a hand?', 'Could you give me a hand with these bags?', 'airport', 'Travel English'),
('I''d like to make a reservation.', 'I''d like to make a reservation for two at 7 PM.', 'restaurant', 'Restaurant English'),
('Is this seat taken?', 'Excuse me, is this seat taken?', 'airport', 'Travel English'),
('Let''s touch base tomorrow.', 'Let''s touch base tomorrow morning about the project.', 'office', 'Business English'),
('I''m just browsing, thanks.', 'I''m just browsing, thanks, I''ll let you know if I need help.', 'shopping', 'Shopping English'),
('Could I get the check, please?', 'Could I get the check, please? We''re in a bit of a hurry.', 'restaurant', 'Restaurant English'),
('Do you have this in a different size?', 'Do you have this in a different size, maybe a medium?', 'shopping', 'Shopping English'),
('I have a reservation under Smith.', 'Hi, I have a reservation under Smith for tonight.', 'hotel', 'Travel English'),
('Let''s circle back on that.', 'Let''s circle back on that once we get more data.', 'office', 'Business English'),
('Could you recommend something local?', 'Could you recommend something local for dinner tonight?', 'restaurant', 'Restaurant English')
ON CONFLICT DO NOTHING;
