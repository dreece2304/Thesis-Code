function [tt,Ut, SOC] = NMC(t_span, SOC0,P)


global R_p1 C_p1 R_p2 C_p2 Q_n w1 w2 w3 
% Define the  constants
R_p1 = 0.0268;
R_p2 = 0.0129;
C_p1 = 1125;
C_p2 = 20701;
Q_n = 150;
w1 = 0;
w2 = 0;
w3 = 0;
R0 = 0.038;
% Define the initial conditions

U_p10 = 0;
U_p20 = 0;
c0(1) = SOC0;
c0(2) = U_p10;
c0(3) = U_p20;


% Now need to calculate the desired charge/discharge for each section. This
% is done using the required power/s (This will probably be taken out this
% function and used in the main script file)

tt = [t_span(1):t_span(2)];

It = [1:length(tt)];
I = ((P)/3.7)/27; % Generate I(t) (I had to divide by the number of cells that were in the overall system)
% Now calculate the approximate solution
[tt,c]=ode45(@(tt,c)ECMSOC(tt,c,I,It),t_span,c0); % This is the ODE solver.

% This is getting the results out of the output matrix
SOC = c(:,1);
U1 = c(:,2);
U2 = c(:,3);
I_actual = interp1(It, I, tt);
OCV = 14.7958*SOC.^6 - 36.6148*SOC.^5 + 29.2355*SOC.^4 - 6.2817*SOC.^3 - 1.6476*SOC.^2 + 1.2866*SOC + 3.4049; % Open circuit voltage. 
Ut = OCV - U1 - U2 - R0.*I_actual; % this is the total voltage.
%SOC_DP = SOC_D/5;



end



